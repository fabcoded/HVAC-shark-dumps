#!/usr/bin/env python3
"""
validate_xye_vs_rt.py — Cross-correlate XYE bus frames against R/T serial frames.

Round 1 (default): Validate 7 hypotheses mapping XYE C0/C3 response fields to
  R/T C0 response fields.  Iterates from R/T (sparse, ~2.5 s polling) and finds
  nearest XYE (dense, ~0.3 s polling) within MAX_DT seconds.

  X-01: Mode           XYE byte[8]   vs R/T C0 body[2] bits[7:5]
  X-02: Set Temp       XYE byte[10]  vs R/T C0 body[2] bits[3:0]+16
  X-03: Fan Speed      XYE byte[9]   vs R/T C0 body[3]
  X-04: Indoor T1      XYE byte[11]  vs R/T C0 body[11]
  X-05: Outdoor T3     XYE byte[14]  vs R/T C0 body[12]
  X-06: Turbo          XYE byte[20]  vs R/T C0 body[10]
  X-07: Run Status     XYE byte[19]  vs R/T C0 body[1]  (exploratory)

Round 2 (--timeline): Extract room controller (KJR-12x) behaviour from XYE bus.
  Builds a condensed timeline of master commands and pattern statistics.

Criteria:
  - At least 20 matched pairs per hypothesis
  - Max 5% deviation for numeric values
  - Comparison frames within MAX_DT = 2.0 s of each other
  - Each session processed independently (no cross-session timestamp mixing)

Usage:
    python validate_xye_vs_rt.py [session_dirs...]
    python validate_xye_vs_rt.py --timeline [session_dirs...]
"""

import struct, sys, os, bisect, argparse, math
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Constants ───────────────────────────────────────────────────────────────

BUS_XYE  = 0x00
BUS_UART = 0x01
BUS_DISP = 0x02
BUS_RT   = 0x03

MAX_DT = 2.0   # seconds — max timestamp gap for a valid pair
DEV_PCT = 5.0  # percent — max deviation for numeric comparisons

# ── Mode mapping tables ─────────────────────────────────────────────────────
# See protocol_shared.md §7

# XYE mode byte → canonical integer (1=Auto,2=Cool,3=Dry,4=Heat,5=Fan,0=Off)
XYE_MODE_TO_CANONICAL = {
    0x00: 0,   # Off
    0x81: 5,   # Fan
    0x82: 3,   # Dry
    0x84: 4,   # Heat
    0x88: 2,   # Cool
    0x90: 1,   # Auto
    0x91: 1,   # Auto + Fan (sub-mode)
    0x94: 1,   # Auto + Heat (sub-mode)
    0x98: 1,   # Auto + Cool (sub-mode)
}

# R/T C0 body[2] bits[7:5] are already canonical: 1=Auto,2=Cool,3=Dry,4=Heat,5=Fan

CANONICAL_MODE_NAMES = {
    0: 'Off', 1: 'Auto', 2: 'Cool', 3: 'Dry', 4: 'Heat', 5: 'Fan',
}

# ── Fan speed mapping tables ────────────────────────────────────────────────
# See protocol_shared.md §6

XYE_FAN_TO_CANONICAL = {
    0x80: 'auto',
    0x01: 'high',
    0x02: 'medium',
    0x04: 'low',
}

RT_FAN_TO_CANONICAL = {
    102: 'auto',
    101: 'auto',    # system-forced Auto in Dry/Auto modes
    100: 'turbo',
    80:  'high',
    60:  'medium',
    40:  'low',
    20:  'silent',
}

XYE_MODE_NAMES = {
    0x00: 'Off', 0x81: 'Fan', 0x82: 'Dry', 0x84: 'Heat', 0x88: 'Cool',
    0x90: 'Auto', 0x91: 'Auto+Fan', 0x94: 'Auto+Heat', 0x98: 'Auto+Cool',
}

XYE_FAN_NAMES = {0x80: 'Auto', 0x01: 'High', 0x02: 'Med', 0x04: 'Low'}

# ── pcap reader ─────────────────────────────────────────────────────────────

def read_pcap(path):
    """Yield (timestamp_sec, raw_bytes) for each packet in a pcap file."""
    with open(path, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return
        magic = struct.unpack('<I', ghdr[0:4])[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            print(f"  WARNING: unknown pcap magic {magic:#x} in {path}")
            return

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', phdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            ts = ts_sec + ts_usec / 1_000_000.0
            yield (ts, data)


def parse_hvac_shark(pkt_data):
    """Parse HVAC_shark header, return (bus_type, protocol_data) or None."""
    # Skip Ethernet(14) + IPv4(20) + UDP(8) = 42 bytes
    if len(pkt_data) < 42 + 13:
        return None
    payload = pkt_data[42:]
    if payload[:10] != b'HVAC_shark':
        return None
    bus_type = payload[11]
    version = payload[12]
    if version == 0x00:
        proto_data = payload[13:]
    elif version == 0x01:
        off = 13
        if off >= len(payload):
            return None
        n = payload[off]; off += 1 + n
        if off >= len(payload):
            return None
        m = payload[off]; off += 1 + m
        if off >= len(payload):
            return None
        c = payload[off]; off += 1 + c
        proto_data = payload[off:]
    else:
        return None
    return (bus_type, bytes(proto_data))


# ── XYE frame decoders ──────────────────────────────────────────────────────

def decode_xye_response(proto):
    """Decode XYE C0/C3 32-byte slave response. Returns dict or None.

    Selection: proto[0]=0xAA, proto[1] in {0xC0,0xC3}, len==32.
    Responses are distinguished from 16-byte commands by frame length alone.
    On real hardware byte[2] is the destination address (typically 0x00),
    NOT the 0x80 direction flag documented in the codeberg Erlang emulator.
    Field offsets per protocol_xye.md §2.2.
    """
    if len(proto) != 32:
        return None
    if proto[0] != 0xAA:
        return None
    if proto[1] not in (0xC0, 0xC3):
        return None

    mode_raw = proto[8]
    return {
        'cmd':         proto[1],
        'mode_raw':    mode_raw,
        'fan_raw':     proto[9],
        'set_temp_c':  proto[10] - 0x40,                   # §7: raw - 0x40 = °C
        't1_c':        (proto[11] - 40) / 2.0,             # §7: (raw-40)/2 = °C
        't2a_c':       (proto[12] - 40) / 2.0,
        't3_c':        (proto[14] - 40) / 2.0,
        'run_status':  proto[19] & 0x01,                   # §2.2 byte[19] bit0
        'turbo':       (proto[20] >> 1) & 1,               # §2.2 byte[20] bit1
        'eco_sleep':   proto[20] & 0x01,                   # §2.2 byte[20] bit0
        'v_swing':     (proto[20] >> 2) & 1,               # §2.2 byte[20] bit2
    }


def decode_xye_d0(proto):
    """Decode XYE D0 32-byte broadcast. Returns dict or None.

    Selection: proto[0]=0xAA, proto[1]=0xD0, len>=32.
    Field offsets per protocol_xye.md §0.4b.
    """
    if len(proto) < 32:
        return None
    if proto[0] != 0xAA or proto[1] != 0xD0:
        return None
    return {
        'mode_raw':   proto[5],
        'fan_raw':    proto[6],
        'set_temp_c': proto[7] - 0x40,
        'swing_raw':  proto[11],
    }


def decode_xye_master_cmd(proto):
    """Decode XYE 16-byte master command. Returns dict or None.

    Selection: proto[0]=0xAA, proto[1] in {0xC0,0xC3,0xC4,0xC6},
               proto[2]!=0x80 (not a response), len>=16.
    """
    if len(proto) != 16:   # commands are exactly 16 bytes
        return None
    if proto[0] != 0xAA:
        return None
    cmd = proto[1]
    if cmd not in (0xC0, 0xC3, 0xC4, 0xC6):
        return None

    result = {
        'cmd':     cmd,
        'dest_id': proto[2],
        'src_id':  proto[3],
    }

    if cmd == 0xC3:
        result['mode_raw']   = proto[6]
        result['fan_raw']    = proto[7]
        result['set_temp_c'] = proto[8] - 0x40  # Follow-Me room temp in C3
    elif cmd == 0xC6:
        result['swing_raw'] = proto[6]
    elif cmd == 0xC4:
        result['magic'] = (proto[6], proto[7])  # expect (0xA5, 0x5A) for enum

    return result


# ── R/T frame decoder ────────────────────────────────────────────────────────

def decode_rt_c0(raw):
    """Decode R/T C0 response (0x55 start). Returns dict or None.

    Extended from validate_mainboard_hypotheses.py to include temperature,
    turbo, and power fields needed for X-04..X-07.
    """
    if len(raw) < 15 or raw[0] != 0x55:
        return None
    if len(raw) < 11:
        return None
    msg_type = raw[10]
    if msg_type != 0x03:  # Response/Notification
        return None
    # body starts at byte[11]; tail: checksum(1) + 0x00(1) + EF(1) = 3
    body_len = len(raw) - 11 - 3
    if body_len < 13:   # need up to body[12] for outdoor temp
        return None
    body = raw[11:]
    cmd_id = body[0]
    if cmd_id != 0xC0:
        return None

    # body[2]: mode bits[7:5] + temperature bits[3:0]
    b2 = body[2]
    mode_bits = (b2 >> 5) & 0x07
    temp_int  = (b2 & 0x0F) + 16
    temp_half = bool(b2 & 0x10)
    set_temp  = temp_int + (0.5 if temp_half else 0.0)

    fan = body[3]

    # body[7]: swing
    swing_raw = body[7] & 0x0F
    h_swing = 1 if (swing_raw & 0x03) else 0
    v_swing = 1 if (swing_raw & 0x0C) else 0

    # body[11]: indoor temperature — (val-50)/2 °C
    indoor_temp_c = (body[11] - 50) / 2.0

    # body[12]: outdoor temperature — (val-50)/2 °C
    outdoor_temp_c = (body[12] - 50) / 2.0

    # body[10] bit1: turbo
    turbo = (body[10] >> 1) & 1

    # body[1] bit0: power ON
    power = body[1] & 0x01

    return {
        'mode_bits':      mode_bits,
        'set_temp':       set_temp,
        'fan':            fan,
        'swing_raw':      swing_raw,
        'h_swing':        h_swing,
        'v_swing':        v_swing,
        'indoor_temp_c':  indoor_temp_c,
        'outdoor_temp_c': outdoor_temp_c,
        'turbo':          turbo,
        'power':          power,
    }


# ── Matching engine ─────────────────────────────────────────────────────────

def find_nearest(ts, sorted_list):
    """Binary search for nearest timestamp in sorted_list of (ts, data)."""
    idx = bisect.bisect_left(sorted_list, (ts,))
    best = None
    best_dt = float('inf')
    for i in (idx - 1, idx):
        if 0 <= i < len(sorted_list):
            dt = abs(sorted_list[i][0] - ts)
            if dt < best_dt:
                best_dt = dt
                best = sorted_list[i]
    return best, best_dt


def is_steady_state(idx, frames, extract_fn, window=1):
    """Check if frame at idx has the same extracted value as its neighbours."""
    val = extract_fn(frames[idx][1])
    for i in range(max(0, idx - window), min(len(frames), idx + window + 1)):
        if i != idx and extract_fn(frames[i][1]) != val:
            return False
    return True


def run_hypothesis(hyp_id, description, search_frames, iter_frames,
                   extract_search, extract_iter, compare_fn,
                   require_iter_steady=True):
    """
    Iterate from the SPARSE side (iter_frames), find nearest in DENSE side
    (search_frames).  When require_iter_steady=True, skip iteration frames
    at transition edges.

    Returns (status, n_total, n_match, n_fail).
    """
    pairs = []
    for it_idx, (ts_it, it_data) in enumerate(iter_frames):
        if require_iter_steady and not is_steady_state(
                it_idx, iter_frames, extract_iter, window=1):
            continue

        nearest, dt = find_nearest(ts_it, search_frames)
        if nearest is None or dt > MAX_DT:
            continue

        search_val = extract_search(nearest[1])
        iter_val   = extract_iter(it_data)
        if search_val is None or iter_val is None:
            continue

        match, dev_pct, detail = compare_fn(search_val, iter_val)
        pairs.append({
            'ts_search': nearest[0], 'ts_iter': ts_it, 'dt': dt,
            'search_val': search_val, 'iter_val': iter_val,
            'match': match, 'dev_pct': dev_pct, 'detail': detail,
        })

    n_total = len(pairs)
    n_match = sum(1 for p in pairs if p['match'])
    n_fail  = n_total - n_match

    # Gather unique value pairs for summary
    value_pairs = {}
    for p in pairs:
        key = (str(p['search_val']), str(p['iter_val']))
        if key not in value_pairs:
            value_pairs[key] = {'match': p['match'], 'detail': p['detail'], 'count': 0}
        value_pairs[key]['count'] += 1

    status = ("PASS" if (n_total >= 20 and n_fail == 0) else
              "INSUFFICIENT DATA" if n_total < 20 else "FAIL")

    print(f"\n{'=' * 72}")
    print(f"  {hyp_id}: {description}")
    print(f"  Pairs: {n_total}  |  Match: {n_match}  |  Fail: {n_fail}  |  Status: {status}")
    print(f"{'=' * 72}")

    for (s_v, i_v), info in sorted(value_pairs.items(), key=lambda x: -x[1]['count']):
        flag = "OK" if info['match'] else "FAIL"
        print(f"  [{flag}] XYE={s_v}  RT={i_v}  ({info['count']}x)  {info['detail']}")

    if n_fail > 0:
        print(f"\n  First 5 failures:")
        fails = [p for p in pairs if not p['match']][:5]
        for p in fails:
            print(f"    t_rt={p['ts_iter']:.3f} dt={p['dt']:.3f}s  "
                  f"XYE={p['search_val']}  RT={p['iter_val']}  {p['detail']}")

    return status, n_total, n_match, n_fail


# ── Comparison functions ────────────────────────────────────────────────────

def compare_mode(xye_val, rt_val):
    """Categorical mode comparison via canonical integer."""
    match = (xye_val == rt_val)
    dev = 0.0 if match else 100.0
    xye_name = CANONICAL_MODE_NAMES.get(xye_val, f"?{xye_val}")
    rt_name  = CANONICAL_MODE_NAMES.get(rt_val, f"?{rt_val}")
    return match, dev, f"XYE:{xye_name}({xye_val}) RT:{rt_name}({rt_val})"


def compare_temperature(xye_val, rt_val):
    """Numeric temperature comparison with DEV_PCT tolerance."""
    if rt_val == 0 and xye_val == 0:
        return True, 0.0, "both 0"
    denom = max(abs(rt_val), 0.01)
    dev = abs(xye_val - rt_val) / denom * 100.0
    match = dev <= DEV_PCT
    return match, dev, f"XYE:{xye_val:.1f}C RT:{rt_val:.1f}C dev:{dev:.1f}%"


def compare_fan(xye_val, rt_val):
    """Categorical fan speed comparison via canonical string."""
    match = (xye_val == rt_val)
    dev = 0.0 if match else 100.0
    return match, dev, f"XYE:{xye_val} RT:{rt_val}"


def compare_bool(xye_val, rt_val):
    """Boolean flag comparison."""
    match = (xye_val == rt_val)
    dev = 0.0 if match else 100.0
    return match, dev, f"XYE:{xye_val} RT:{rt_val}"


# ── Session processing ──────────────────────────────────────────────────────

def process_session(pcap_path, session_label):
    """Extract XYE and R/T frames from a single session pcap.

    Returns dict with sorted frame lists:
      'xye_resp': [(ts, decoded_dict), ...]   C0/C3 32-byte responses
      'xye_d0':   [(ts, decoded_dict), ...]   D0 broadcasts
      'xye_cmds': [(ts, decoded_dict), ...]   16-byte master commands
      'rt_c0':    [(ts, decoded_dict), ...]   R/T C0 responses
    """
    xye_resp = []
    xye_d0   = []
    xye_cmds = []
    rt_c0    = []

    for ts, pkt_data in read_pcap(pcap_path):
        parsed = parse_hvac_shark(pkt_data)
        if parsed is None:
            continue
        bus_type, proto = parsed

        if bus_type == BUS_XYE:
            r = decode_xye_response(proto)
            if r is not None:
                xye_resp.append((ts, r))
                continue
            d = decode_xye_d0(proto)
            if d is not None:
                xye_d0.append((ts, d))
                continue
            m = decode_xye_master_cmd(proto)
            if m is not None:
                xye_cmds.append((ts, m))

        elif bus_type == BUS_RT:
            r = decode_rt_c0(proto)
            if r is not None:
                rt_c0.append((ts, r))

    # Sort by timestamp (should already be ordered, but be safe)
    xye_resp.sort(key=lambda x: x[0])
    xye_d0.sort(key=lambda x: x[0])
    xye_cmds.sort(key=lambda x: x[0])
    rt_c0.sort(key=lambda x: x[0])

    return {
        'xye_resp': xye_resp,
        'xye_d0':   xye_d0,
        'xye_cmds': xye_cmds,
        'rt_c0':    rt_c0,
    }


# ── Round 1: Validation ────────────────────────────────────────────────────

def run_validation(session_dirs):
    """Run all 7 hypotheses across sessions, report per-session + overall."""
    all_results = []

    for d in session_dirs:
        pcap = Path(d) / "session.pcap"
        if not pcap.exists():
            print(f"[skip] {d}: no session.pcap")
            continue
        label = Path(d).name
        print(f"\n[read] {label} — {pcap}")
        frames = process_session(str(pcap), label)
        print(f"       XYE C0/C3 responses: {len(frames['xye_resp']):>5}")
        print(f"       XYE D0 broadcasts  : {len(frames['xye_d0']):>5}")
        print(f"       XYE master commands : {len(frames['xye_cmds']):>5}")
        print(f"       R/T C0 responses    : {len(frames['rt_c0']):>5}")

        if not frames['xye_resp'] or not frames['rt_c0']:
            print(f"       Skipping — insufficient data on one or both buses")
            continue

        xye = frames['xye_resp']
        rt  = frames['rt_c0']

        session_results = []

        # X-01: Mode
        s, n, m, f_ = run_hypothesis(
            "X-01", f"Mode ({label})",
            xye, rt,
            lambda x: XYE_MODE_TO_CANONICAL.get(x['mode_raw']),
            lambda r: r['mode_bits'],
            compare_mode,
        )
        session_results.append(("X-01", "Mode", s, n, m, f_))

        # X-02: Set Temperature
        s, n, m, f_ = run_hypothesis(
            "X-02", f"Set Temperature ({label})",
            xye, rt,
            lambda x: float(x['set_temp_c']),
            lambda r: r['set_temp'],
            compare_temperature,
        )
        session_results.append(("X-02", "Set Temp", s, n, m, f_))

        # X-03: Fan Speed
        s, n, m, f_ = run_hypothesis(
            "X-03", f"Fan Speed ({label})",
            xye, rt,
            lambda x: XYE_FAN_TO_CANONICAL.get(x['fan_raw']),
            lambda r: RT_FAN_TO_CANONICAL.get(r['fan']),
            compare_fan,
        )
        session_results.append(("X-03", "Fan Speed", s, n, m, f_))

        # X-04: Indoor Temperature (T1)
        # Filter out XYE frames where T1 raw=0x00 (sensor not reporting → -20°C)
        s, n, m, f_ = run_hypothesis(
            "X-04", f"Indoor Temp T1 ({label})",
            xye, rt,
            lambda x: x['t1_c'] if x['t1_c'] > -19.0 else None,
            lambda r: r['indoor_temp_c'],
            compare_temperature,
        )
        session_results.append(("X-04", "Indoor T1", s, n, m, f_))

        # X-05: Outdoor Temperature (T3)
        # Filter out XYE frames where T3 raw=0x00 (sensor not reporting → -20°C)
        # and R/T frames where outdoor temp is implausible (>100°C → raw=0xFF sentinel)
        s, n, m, f_ = run_hypothesis(
            "X-05", f"Outdoor Temp T3 ({label})",
            xye, rt,
            lambda x: x['t3_c'] if x['t3_c'] > -19.0 else None,
            lambda r: r['outdoor_temp_c'] if r['outdoor_temp_c'] < 100.0 else None,
            compare_temperature,
        )
        session_results.append(("X-05", "Outdoor T3", s, n, m, f_))

        # X-06: Turbo
        s, n, m, f_ = run_hypothesis(
            "X-06", f"Turbo flag ({label})",
            xye, rt,
            lambda x: x['turbo'],
            lambda r: r['turbo'],
            compare_bool,
        )
        session_results.append(("X-06", "Turbo", s, n, m, f_))

        # X-07: Run Status / Power (exploratory)
        s, n, m, f_ = run_hypothesis(
            "X-07", f"Run Status / Power ({label}) [exploratory]",
            xye, rt,
            lambda x: x['run_status'],
            lambda r: r['power'],
            compare_bool,
            require_iter_steady=False,  # exploratory — don't filter
        )
        session_results.append(("X-07", "Run/Power", s, n, m, f_))

        all_results.append((label, session_results))

    # ── Final summary ────────────────────────────────────────────────────
    if not all_results:
        print("\nNo sessions with sufficient data.")
        return

    print(f"\n{'#' * 72}")
    print(f"  CROSS-BUS VALIDATION SUMMARY (XYE ↔ R/T)")
    print(f"  Tolerance: {DEV_PCT}% numeric, categorical exact")
    print(f"  Max time delta: {MAX_DT} s")
    print(f"{'#' * 72}")

    # Aggregate across sessions
    agg = {}  # hyp_id -> (name, total_pairs, total_match, total_fail)
    for label, results in all_results:
        for hyp_id, name, status, n, m, f_ in results:
            if hyp_id not in agg:
                agg[hyp_id] = [name, 0, 0, 0]
            agg[hyp_id][1] += n
            agg[hyp_id][2] += m
            agg[hyp_id][3] += f_

    print(f"\n  {'ID':<6} {'Field':<14} {'Status':<20} {'Pairs':>6} {'Match':>6} {'Fail':>6}")
    print(f"  {'-' * 64}")
    for hyp_id in sorted(agg.keys()):
        name, n, m, f_ = agg[hyp_id]
        status = ("PASS" if (n >= 20 and f_ == 0) else
                  "INSUFFICIENT DATA" if n < 20 else "FAIL")
        print(f"  {hyp_id:<6} {name:<14} {status:<20} {n:>6} {m:>6} {f_:>6}")
    print()


# ── Round 2: Timeline ───────────────────────────────────────────────────────

def build_timeline(frames):
    """Build a list of timeline events from XYE frames.

    Returns list of dicts with keys: ts, type, details.
    """
    events = []

    # Merge all XYE frames into one sorted list with type tags
    all_xye = []
    for ts, d in frames['xye_resp']:
        all_xye.append((ts, 'resp', d))
    for ts, d in frames['xye_d0']:
        all_xye.append((ts, 'd0', d))
    for ts, d in frames['xye_cmds']:
        all_xye.append((ts, 'cmd', d))
    all_xye.sort(key=lambda x: x[0])

    prev_state = {}  # track mode, fan, set_temp, swing for change detection

    for ts, tag, data in all_xye:
        if tag == 'cmd':
            cmd = data['cmd']
            if cmd == 0xC0:
                events.append({'ts': ts, 'type': 'C0_query',
                               'dest': data['dest_id'], 'details': ''})
            elif cmd == 0xC3:
                mode_name = XYE_MODE_NAMES.get(data.get('mode_raw'), '?')
                fan_name  = XYE_FAN_NAMES.get(data.get('fan_raw'), '?')
                temp = data.get('set_temp_c', '?')
                cur = {'mode': data.get('mode_raw'),
                       'fan': data.get('fan_raw'),
                       'temp': temp}
                changes = []
                for k in ('mode', 'fan', 'temp'):
                    if k in prev_state and prev_state[k] != cur[k]:
                        if k == 'mode':
                            old_name = XYE_MODE_NAMES.get(prev_state[k], f'0x{prev_state[k]:02X}')
                            changes.append(f"mode:{old_name}->{mode_name}")
                        elif k == 'fan':
                            old_name = XYE_FAN_NAMES.get(prev_state[k], f'0x{prev_state[k]:02X}')
                            changes.append(f"fan:{old_name}->{fan_name}")
                        elif k == 'temp':
                            changes.append(f"temp:{prev_state[k]}->{temp}")
                prev_state.update(cur)
                change_str = f"  [{', '.join(changes)}]" if changes else ""
                events.append({
                    'ts': ts, 'type': 'C3_set', 'dest': data['dest_id'],
                    'details': f"mode={mode_name} fan={fan_name} temp={temp}C{change_str}",
                })
            elif cmd == 0xC4:
                magic = data.get('magic', (0, 0))
                is_enum = (magic == (0xA5, 0x5A))
                events.append({
                    'ts': ts, 'type': 'C4_enum' if is_enum else 'C4_query',
                    'dest': data['dest_id'],
                    'details': f"addr=0x{data['dest_id']:02X}",
                })
            elif cmd == 0xC6:
                swing = data.get('swing_raw', 0)
                swing_name = {0x00: 'Off', 0x10: 'V-swing', 0x20: 'H-swing'}.get(
                    swing, f'0x{swing:02X}')
                events.append({
                    'ts': ts, 'type': 'C6_follow',
                    'dest': data.get('dest_id', 0),
                    'details': f"swing={swing_name}",
                })

        elif tag == 'resp':
            # Only log responses that carry useful state — skip for timeline
            # (they're echoes of the preceding command)
            pass

        elif tag == 'd0':
            # D0 broadcasts logged only if state changed
            mode_name = XYE_MODE_NAMES.get(data['mode_raw'], '?')
            fan_name  = XYE_FAN_NAMES.get(data['fan_raw'], '?')
            swing = data.get('swing_raw', 0)
            swing_name = {0x00: 'Off', 0x10: 'V', 0x20: 'H'}.get(
                swing, f'0x{swing:02X}')
            d0_state = (data['mode_raw'], data['fan_raw'],
                        data['set_temp_c'], swing)
            if d0_state != prev_state.get('_d0_last'):
                prev_state['_d0_last'] = d0_state
                events.append({
                    'ts': ts, 'type': 'D0_bcast',
                    'dest': 0,
                    'details': f"{mode_name}/{fan_name}/{data['set_temp_c']}C/sw={swing_name}",
                })

    return events


def analyze_patterns(frames, events):
    """Compute polling and pairing statistics from XYE frames."""
    stats = {}

    # C0 query intervals
    c0_ts = [ts for ts, d in frames['xye_cmds'] if d['cmd'] == 0xC0]
    if len(c0_ts) > 1:
        deltas = [c0_ts[i+1] - c0_ts[i] for i in range(len(c0_ts)-1)]
        stats['c0_interval'] = {
            'mean': sum(deltas) / len(deltas),
            'min':  min(deltas),
            'max':  max(deltas),
            'n':    len(c0_ts),
        }

    # D0 broadcast intervals
    d0_ts = [ts for ts, _ in frames['xye_d0']]
    if len(d0_ts) > 1:
        deltas = [d0_ts[i+1] - d0_ts[i] for i in range(len(d0_ts)-1)]
        stats['d0_interval'] = {
            'mean': sum(deltas) / len(deltas),
            'min':  min(deltas),
            'max':  max(deltas),
            'n':    len(d0_ts),
        }

    # C3+C6 pairing: C6 should follow C3 within 100 ms
    c3_ts = [(ts, d) for ts, d in frames['xye_cmds'] if d['cmd'] == 0xC3]
    c6_ts = [(ts, d) for ts, d in frames['xye_cmds'] if d['cmd'] == 0xC6]
    paired = 0
    for ts3, _ in c3_ts:
        for ts6, _ in c6_ts:
            if 0 < (ts6 - ts3) < 0.100:
                paired += 1
                break
    stats['c3c6_pairing'] = {
        'c3_count': len(c3_ts),
        'c6_count': len(c6_ts),
        'paired':   paired,
        'rate':     (paired / len(c3_ts) * 100) if c3_ts else 0,
    }

    # C4 enumeration: count distinct addresses probed
    c4_frames = [(ts, d) for ts, d in frames['xye_cmds'] if d['cmd'] == 0xC4]
    c4_addrs = set(d['dest_id'] for _, d in c4_frames)
    # Check for responses: any C4 32-byte response in xye_resp?
    c4_responses = [(ts, d) for ts, d in frames['xye_resp'] if d['cmd'] == 0xC4]
    stats['c4_enum'] = {
        'total_probes': len(c4_frames),
        'distinct_addrs': sorted(c4_addrs),
        'responses': len(c4_responses),
    }

    # Follow-Me temp changes: distinct values of C3 byte[8] (set_temp_c)
    c3_temps = [d['set_temp_c'] for _, d in c3_ts if 'set_temp_c' in d]
    stats['followme_temps'] = {
        'distinct': sorted(set(c3_temps)),
        'count': len(c3_temps),
    }

    return stats


def print_timeline(events, stats, session_label):
    """Print condensed timeline and statistics for one session."""
    print(f"\n{'=' * 72}")
    print(f"  {session_label} — Room Controller Timeline")
    print(f"{'=' * 72}")

    # Condensed timeline: suppress repetitive C0 queries
    c0_count = 0
    for ev in events:
        if ev['type'] == 'C0_query':
            c0_count += 1
            continue  # suppress individual queries
        if c0_count > 0:
            print(f"  ... ({c0_count} C0 queries)")
            c0_count = 0
        dest = ev.get('dest', '')
        dest_str = f"addr=0x{dest:02X}" if isinstance(dest, int) and dest >= 0 else ""
        print(f"  {ev['ts']:>9.3f}  {ev['type']:<12} {dest_str:<12} {ev['details']}")
    if c0_count > 0:
        print(f"  ... ({c0_count} C0 queries)")

    # Statistics
    print(f"\n  Polling Statistics:")
    if 'c0_interval' in stats:
        s = stats['c0_interval']
        print(f"    C0 query interval:  mean={s['mean']:.3f}s  "
              f"min={s['min']:.3f}s  max={s['max']:.3f}s  n={s['n']}")
    if 'd0_interval' in stats:
        s = stats['d0_interval']
        print(f"    D0 broadcast:       mean={s['mean']:.3f}s  "
              f"min={s['min']:.3f}s  max={s['max']:.3f}s  n={s['n']}")
    if 'c3c6_pairing' in stats:
        s = stats['c3c6_pairing']
        print(f"    C3+C6 pair rate:    {s['paired']}/{s['c3_count']} = {s['rate']:.1f}%"
              f"  (C6 count: {s['c6_count']})")
    if 'c4_enum' in stats:
        s = stats['c4_enum']
        addrs = [f"0x{a:02X}" for a in s['distinct_addrs']]
        print(f"    C4 enumeration:     {s['total_probes']} probes, "
              f"{len(s['distinct_addrs'])} addresses [{', '.join(addrs)}], "
              f"{s['responses']} responses")
    if 'followme_temps' in stats:
        s = stats['followme_temps']
        print(f"    Follow-Me temps:    {len(s['distinct'])} distinct values "
              f"over {s['count']} C3 frames: {s['distinct']}")
    print()


def run_timeline(session_dirs):
    """Run Round 2 timeline extraction for each session."""
    for d in session_dirs:
        pcap = Path(d) / "session.pcap"
        if not pcap.exists():
            print(f"[skip] {d}: no session.pcap")
            continue
        label = Path(d).name
        print(f"\n[read] {label} — {pcap}")
        frames = process_session(str(pcap), label)
        print(f"       XYE responses : {len(frames['xye_resp']):>5}")
        print(f"       XYE D0        : {len(frames['xye_d0']):>5}")
        print(f"       XYE commands  : {len(frames['xye_cmds']):>5}")

        if not frames['xye_cmds'] and not frames['xye_d0']:
            print(f"       Skipping — no XYE data")
            continue

        events = build_timeline(frames)
        stats  = analyze_patterns(frames, events)
        print_timeline(events, stats, label)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='XYE ↔ R/T cross-bus validation and room controller analysis')
    parser.add_argument('sessions', nargs='*', help='Session directories')
    parser.add_argument('--timeline', action='store_true',
                        help='Round 2: extract room controller behaviour timeline')
    args = parser.parse_args()

    # Default sessions: 3-9
    if not args.sessions:
        script_dir = Path(os.path.abspath(__file__)).parent
        base = script_dir.parent.parent / 'Midea-XtremeSaveBlue-display'
        args.sessions = [str(base / f'Session {i}') for i in range(3, 10)
                         if (base / f'Session {i}').exists()]

    if not args.sessions:
        print("No session directories found. Pass paths as arguments.")
        sys.exit(1)

    print(f"Sessions: {[Path(d).name for d in args.sessions]}")

    if args.timeline:
        run_timeline(args.sessions)
    else:
        run_validation(args.sessions)


if __name__ == '__main__':
    main()
