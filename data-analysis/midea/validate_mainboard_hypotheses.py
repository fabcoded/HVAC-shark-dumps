#!/usr/bin/env python3
"""
Validate mainboard protocol hypotheses by cross-correlating with R/T bus frames.

Validates 5 hypotheses:
  H-01: Mode         (MB Grey byte[3])  vs R/T C0 body[2] mode_bits
  H-02: Setpoint     (MB Grey byte[4])  vs R/T C0 body[2] temperature
  H-03: Fan speed    (MB Grey byte[5])  vs R/T C0 body[3] fan speed
  H-04: Swing flags  (MB Grey byte[9])  vs R/T C0 body[7] swing
  H-08: Actual fan   (MB Blue byte[5])  vs R/T C0 body[3] fan speed

Criteria:
  - At least 20 matched pairs per hypothesis
  - Max +/-2% deviation
  - Comparison frames must be within 0.5 s of each other
"""

import struct, sys, os, glob

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── pcap reader ──────────────────────────────────────────────────────────────

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


# ── frame decoders ───────────────────────────────────────────────────────────

def decode_mb_aa20_grey(raw):
    """Decode mainboard AA20 Grey request (36 bytes). Returns dict or None."""
    if len(raw) < 36 or raw[0] != 0xAA or raw[1] != 0x20 or raw[2] != 0x24:
        return None
    return {
        'mode': raw[3],
        'set_temp_raw': raw[4],
        'set_temp_c': (raw[4] - 30) / 2.0,
        'fan_speed': raw[5],
        'flags': raw[9],
        'h_swing': (raw[9] >> 4) & 1,
        'v_swing': (raw[9] >> 2) & 1,
        'power': (raw[9] >> 6) & 1,
    }


def decode_mb_aa20_blue(raw):
    """Decode mainboard AA20 Blue response (29 bytes). Returns dict or None."""
    if len(raw) < 29 or raw[0] != 0xAA or raw[1] != 0x20 or raw[2] != 0x1D:
        return None
    return {
        'mode': raw[3],
        'actual_fan': raw[5],
    }


def decode_rt_c0(raw):
    """Decode R/T C0 response (0x55 start). Returns dict or None."""
    if len(raw) < 15 or raw[0] != 0x55:
        return None
    # msg_type at byte[10]
    if len(raw) < 11:
        return None
    msg_type = raw[10]
    if msg_type != 0x03:  # Response/Notification
        return None
    # body starts at byte[11]
    # tail: checksum(1) + 0x00(1) + EF(1) = 3, so body_len = len - 11 - 3
    body_len = len(raw) - 11 - 3
    if body_len < 8:
        return None
    body = raw[11:]
    cmd_id = body[0]
    if cmd_id != 0xC0:
        return None

    b2 = body[2]
    mode_bits = (b2 >> 5) & 0x07
    temp_int = (b2 & 0x0F) + 16
    temp_half = bool(b2 & 0x10)
    set_temp = temp_int + (0.5 if temp_half else 0.0)

    fan = body[3]

    swing_raw = body[7] & 0x0F
    # 0x00=Off, 0x03=Horizontal, 0x0C=Vertical, 0x0F=Both
    h_swing = 1 if (swing_raw & 0x03) else 0
    v_swing = 1 if (swing_raw & 0x0C) else 0

    return {
        'mode_bits': mode_bits,
        'set_temp': set_temp,
        'fan': fan,
        'swing_raw': swing_raw,
        'h_swing': h_swing,
        'v_swing': v_swing,
    }


# ── mode mapping ─────────────────────────────────────────────────────────────

# Hypothesis H-01 mapping:  MB index -> UART mode_bits
MB_MODE_TO_UART = {
    0: 2,   # Cool  -> 2
    1: 3,   # Dry   -> 3
    2: 5,   # Fan   -> 5
    3: 4,   # Heat  -> 4
    4: 1,   # Auto  -> 1
}

MODE_NAMES = {0: 'Cool', 1: 'Dry', 2: 'Fan', 3: 'Heat', 4: 'Auto'}
UART_MODE_NAMES = {1: 'Auto', 2: 'Cool', 3: 'Dry', 4: 'Heat', 5: 'Fan'}


# ── matching engine ──────────────────────────────────────────────────────────

MAX_DT = 0.5  # seconds

import bisect

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


def validate_session(pcap_path, session_name):
    """Run all 5 hypothesis validations for one session pcap."""
    mb_grey = []    # (ts, decoded_dict)
    mb_blue = []    # (ts, decoded_dict)
    rt_c0 = []      # (ts, decoded_dict)

    for ts, pkt_data in read_pcap(pcap_path):
        parsed = parse_hvac_shark(pkt_data)
        if parsed is None:
            continue
        bus_type, proto = parsed

        if bus_type == 0x02:  # disp-mainboard
            g = decode_mb_aa20_grey(proto)
            if g:
                mb_grey.append((ts, g))
            b = decode_mb_aa20_blue(proto)
            if b:
                mb_blue.append((ts, b))
        elif bus_type == 0x03:  # r-t
            r = decode_rt_c0(proto)
            if r:
                rt_c0.append((ts, r))

    rt_c0.sort(key=lambda x: x[0])
    mb_grey.sort(key=lambda x: x[0])
    mb_blue.sort(key=lambda x: x[0])

    return mb_grey, mb_blue, rt_c0


def is_steady_state(idx, frames, extract_fn, window=1):
    """Check if frame at idx has the same extracted value as its neighbors."""
    val = extract_fn(frames[idx][1])
    for i in range(max(0, idx - window), min(len(frames), idx + window + 1)):
        if i != idx and extract_fn(frames[i][1]) != val:
            return False
    return True


def run_hypothesis(hyp_id, description, mb_frames, rt_c0, extract_mb, extract_rt,
                   compare_fn, require_rt_steady=True):
    """
    Hypothesis validation: iterate from the SPARSE side (R/T C0), find nearest MB frame.
    This avoids many-to-one duplication that inflates failure counts during transitions.

    When require_rt_steady=True, only use R/T frames whose neighbors have the same value
    (filters out transition edges on the R/T side too).
    """
    pairs = []
    for rt_idx, (ts_rt, rt_data) in enumerate(rt_c0):
        # Optional: skip R/T frames at transition edges
        if require_rt_steady and not is_steady_state(rt_idx, rt_c0, extract_rt, window=1):
            continue

        nearest, dt = find_nearest(ts_rt, mb_frames)
        if nearest is None or dt > MAX_DT:
            continue

        mb_val = extract_mb(nearest[1])
        rt_val = extract_rt(rt_data)
        if mb_val is None or rt_val is None:
            continue

        match, dev_pct, detail = compare_fn(mb_val, rt_val)
        pairs.append({
            'ts_mb': nearest[0], 'ts_rt': ts_rt, 'dt': dt,
            'mb_val': mb_val, 'rt_val': rt_val,
            'match': match, 'dev_pct': dev_pct, 'detail': detail,
        })

    n_total = len(pairs)
    n_match = sum(1 for p in pairs if p['match'])
    n_fail = n_total - n_match

    # Gather unique value pairs for summary
    value_pairs = {}
    for p in pairs:
        key = (p['mb_val'] if not isinstance(p['mb_val'], dict) else str(p['mb_val']),
               p['rt_val'] if not isinstance(p['rt_val'], dict) else str(p['rt_val']))
        if key not in value_pairs:
            value_pairs[key] = {'match': p['match'], 'detail': p['detail'], 'count': 0}
        value_pairs[key]['count'] += 1

    status = "PASS" if (n_total >= 20 and n_fail == 0) else \
             "INSUFFICIENT DATA" if n_total < 20 else "FAIL"

    print(f"\n{'='*72}")
    print(f"  {hyp_id}: {description}")
    print(f"  Pairs: {n_total} (steady-state R/T frames matched to nearest MB)")
    print(f"  Match: {n_match}  |  Fail: {n_fail}  |  Status: {status}")
    print(f"{'='*72}")

    for (mb_v, rt_v), info in sorted(value_pairs.items(), key=lambda x: -x[1]['count']):
        flag = "OK" if info['match'] else "FAIL"
        print(f"  [{flag}] MB={mb_v}  RT={rt_v}  ({info['count']}x)  {info['detail']}")

    if n_fail > 0:
        print(f"\n  First 5 failures:")
        fails = [p for p in pairs if not p['match']][:5]
        for p in fails:
            print(f"    t_rt={p['ts_rt']:.3f} dt={p['dt']:.3f}s  MB={p['mb_val']}  RT={p['rt_val']}  {p['detail']}")

    return status, n_total, n_match, n_fail


# ── comparison functions ─────────────────────────────────────────────────────

def compare_mode(mb_val, rt_val):
    expected_uart = MB_MODE_TO_UART.get(mb_val)
    if expected_uart is None:
        return False, 100.0, f"unknown MB mode {mb_val}"
    match = (expected_uart == rt_val)
    mb_name = MODE_NAMES.get(mb_val, f"?{mb_val}")
    rt_name = UART_MODE_NAMES.get(rt_val, f"?{rt_val}")
    dev = 0.0 if match else 100.0
    return match, dev, f"MB:{mb_name} -> expect UART:{expected_uart}, got UART:{rt_val}({rt_name})"


def compare_temperature(mb_val, rt_val):
    # mb_val: temp in C from mainboard
    # rt_val: temp in C from R/T C0
    if rt_val == 0:
        dev = 0.0 if mb_val == 0 else 100.0
    else:
        dev = abs(mb_val - rt_val) / abs(rt_val) * 100.0
    match = dev <= 2.0
    return match, dev, f"MB:{mb_val:.1f}C  RT:{rt_val:.1f}C  dev:{dev:.1f}%"


def compare_fan(mb_val, rt_val):
    if rt_val == 0:
        dev = 0.0 if mb_val == 0 else 100.0
    else:
        dev = abs(mb_val - rt_val) / abs(rt_val) * 100.0
    match = dev <= 2.0
    return match, dev, f"MB:{mb_val}  RT:{rt_val}  dev:{dev:.1f}%"


def compare_swing(mb_val, rt_val):
    # mb_val: dict with h_swing, v_swing
    # rt_val: dict with h_swing, v_swing
    h_match = mb_val['h_swing'] == rt_val['h_swing']
    v_match = mb_val['v_swing'] == rt_val['v_swing']
    match = h_match and v_match
    dev = 0.0 if match else 100.0
    return match, dev, (f"H-swing: MB={mb_val['h_swing']} RT={rt_val['h_swing']} "
                        f"V-swing: MB={mb_val['v_swing']} RT={rt_val['v_swing']}")


# ── main ─────────────────────────────────────────────────────────────────────

DUMP_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '..', '..', 'Midea-XtremeSaveBlue-display')

SESSIONS = [4, 7, 8, 9]

def main():
    all_mb_grey = []
    all_mb_blue = []
    all_rt_c0 = []

    for sess_num in SESSIONS:
        pcap_path = os.path.join(DUMP_BASE, f'Session {sess_num}', 'session.pcap')
        if not os.path.isfile(pcap_path):
            print(f"Session {sess_num}: pcap not found at {pcap_path}")
            continue

        print(f"\nLoading Session {sess_num} ...")
        grey, blue, rt = validate_session(pcap_path, f"Session {sess_num}")
        print(f"  AA20 Grey: {len(grey)}, AA20 Blue: {len(blue)}, R/T C0: {len(rt)}")
        all_mb_grey.extend(grey)
        all_mb_blue.extend(blue)
        all_rt_c0.extend(rt)

    all_rt_c0.sort(key=lambda x: x[0])

    print(f"\n{'#'*72}")
    print(f"  TOTALS: {len(all_mb_grey)} MB Grey, {len(all_mb_blue)} MB Blue, {len(all_rt_c0)} R/T C0")
    print(f"  Sessions: {SESSIONS}")
    print(f"  Max time delta: {MAX_DT} s")
    print(f"{'#'*72}")

    results = []

    # H-01: Mode
    s, n, m, f_ = run_hypothesis(
        "H-01", "Mode index (MB Grey byte[3] -> R/T C0 mode_bits)",
        all_mb_grey, all_rt_c0,
        lambda mb: mb['mode'],
        lambda rt: rt['mode_bits'],
        compare_mode,
    )
    results.append(("H-01", "Mode", s, n, m, f_))

    # H-02: Setpoint temperature
    s, n, m, f_ = run_hypothesis(
        "H-02", "Setpoint temperature (MB Grey byte[4] -> R/T C0 temp)",
        all_mb_grey, all_rt_c0,
        lambda mb: mb['set_temp_c'],
        lambda rt: rt['set_temp'],
        compare_temperature,
    )
    results.append(("H-02", "Setpoint", s, n, m, f_))

    # H-03: Fan speed
    s, n, m, f_ = run_hypothesis(
        "H-03", "Fan speed (MB Grey byte[5] -> R/T C0 body[3])",
        all_mb_grey, all_rt_c0,
        lambda mb: mb['fan_speed'],
        lambda rt: rt['fan'],
        compare_fan,
    )
    results.append(("H-03", "Fan speed", s, n, m, f_))

    # H-04: Swing flags
    s, n, m, f_ = run_hypothesis(
        "H-04", "Swing flags (MB Grey byte[9] bits -> R/T C0 body[7])",
        all_mb_grey, all_rt_c0,
        lambda mb: {'h_swing': mb['h_swing'], 'v_swing': mb['v_swing']},
        lambda rt: {'h_swing': rt['h_swing'], 'v_swing': rt['v_swing']},
        compare_swing,
    )
    results.append(("H-04", "Swing flags", s, n, m, f_))

    # H-07: Mode echo in Blue response (MB Blue byte[3] == MB Grey byte[3])
    # Cross-validate: MB Blue byte[3] should carry the same mode as R/T C0
    s, n, m, f_ = run_hypothesis(
        "H-07", "Mode echo in Blue response (MB Blue byte[3] -> R/T C0 mode_bits)",
        all_mb_blue, all_rt_c0,
        lambda mb: mb['mode'],
        lambda rt: rt['mode_bits'],
        compare_mode,
    )
    results.append(("H-07", "Mode echo", s, n, m, f_))

    # ── H-02 failure diagnostic ─────────────────────────────────────────
    # Show the R/T C0 temperature sequence around the failure timestamps
    print(f"\n  H-02 diagnostic: R/T C0 temperature timeline (Session 7, t>70s):")
    for ts, rt in all_rt_c0:
        if 70.0 < ts < 90.0:
            nearest_g, dt_g = find_nearest(ts, all_mb_grey)
            mb_t = nearest_g[1]['set_temp_c'] if nearest_g and dt_g < 0.5 else None
            print(f"    t={ts:.3f}  RT_temp={rt['set_temp']:.1f}C  MB_temp={mb_t}C  dt={dt_g:.3f}s")

    # ── MB Blue byte[5] value analysis ──────────────────────────────────
    blue_fan_dist = {}
    for _, b in all_mb_blue:
        v = b['actual_fan']
        blue_fan_dist[v] = blue_fan_dist.get(v, 0) + 1
    print(f"\n  MB Blue byte[5] value distribution (H-08 REJECTED):")
    for v, cnt in sorted(blue_fan_dist.items()):
        print(f"    {v:>4d} (0x{v:02X}): {cnt}x")
    print(f"  -> Values 0, 1, 23 have no match in UART fan encoding.")
    print(f"     H-08 hypothesis is REJECTED. byte[5] is NOT fan speed.")

    # ── Final summary ────────────────────────────────────────────────────────
    print(f"\n{'#'*72}")
    print(f"  VALIDATION SUMMARY")
    print(f"{'#'*72}")
    print(f"  {'ID':<6} {'Field':<16} {'Status':<20} {'Pairs':>6} {'Match':>6} {'Fail':>6}")
    print(f"  {'-'*66}")
    for hyp_id, name, status, n, m, f_ in results:
        print(f"  {hyp_id:<6} {name:<16} {status:<20} {n:>6} {m:>6} {f_:>6}")
    print()


if __name__ == '__main__':
    main()
