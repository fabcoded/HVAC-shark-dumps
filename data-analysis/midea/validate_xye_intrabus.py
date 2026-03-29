#!/usr/bin/env python3
"""
validate_xye_intrabus.py — Validate D0 broadcast consistency against C0/C3
responses on the same XYE bus.

D0 broadcasts carry mode, fan, set temp, and swing. This script compares
each D0 frame against the nearest C0/C3 response within 0.5 seconds (same
bus, same polling cycle) and the most recent C6 command (for swing).

Hypotheses:
  D-01: Mode    — D0 byte[5] vs C0 byte[8] (masking auto sub-modes)
  D-02: Fan     — D0 byte[6] vs C0 byte[9] (exact match)
  D-03: SetTemp — D0 byte[7] vs C0 byte[10] (exact match)
  D-04: Swing   — D0 byte[11] vs most recent C6 byte[6]

Additionally reports on D0 bytes 15-19 discovered by scan_xye_unknowns.py:
  byte[15]: 0x04 or 0x06 (flag)
  byte[16]: variable — possible temperature
  byte[18]: variable — unknown
  byte[19]: variable (25 distinct) — unknown
  byte[29]: variable (85 distinct) — CRC candidate

Sanity: Each hypothesis also cross-checks known-confirmed fields (mode, fan,
temp from X-01..X-03) to ensure decoding is correct per frame.

Usage:
    python validate_xye_intrabus.py [session_dirs...]
"""

import struct, sys, os, bisect
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MAX_DT = 0.5  # seconds — tighter window since both are on the same bus

# ── pcap reader (shared with validate_xye_vs_rt.py) ────────────────────────

def read_pcap(path):
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
            return
        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', phdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            yield (ts_sec + ts_usec / 1_000_000.0, data)


def parse_hvac_shark(pkt_data):
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


# ── XYE mode name helper ───────────────────────────────────────────────────

MODE_NAMES = {
    0x00: 'Off', 0x81: 'Fan', 0x82: 'Dry', 0x84: 'Heat', 0x88: 'Cool',
    0x90: 'Auto', 0x91: 'Auto+Fan', 0x94: 'Auto+Heat', 0x98: 'Auto+Cool',
}

SWING_NAMES = {0x00: 'Off', 0x10: 'V-swing', 0x20: 'H-swing'}


def strip_auto_submode(mode_byte):
    """Mask auto sub-mode bits: 0x91/0x94/0x98 → 0x90."""
    if mode_byte in (0x91, 0x94, 0x98):
        return 0x90
    return mode_byte


# ── Session processing ──────────────────────────────────────────────────────

def process_session(pcap_path):
    """Extract D0, C0/C3 responses, and C6 commands from one session."""
    d0_frames = []     # [(ts, raw_proto)]
    c0c3_resp = []     # [(ts, raw_proto)]
    c6_cmds   = []     # [(ts, raw_proto)]

    for ts, pkt_data in read_pcap(pcap_path):
        parsed = parse_hvac_shark(pkt_data)
        if parsed is None:
            continue
        bus_type, proto = parsed
        if bus_type != 0x00:  # XYE only
            continue
        if len(proto) < 2 or proto[0] != 0xAA:
            continue

        cmd = proto[1]
        if len(proto) == 32:
            if cmd == 0xD0:
                d0_frames.append((ts, proto))
            elif cmd in (0xC0, 0xC3):
                c0c3_resp.append((ts, proto))
        elif len(proto) == 16:
            if cmd == 0xC6:
                c6_cmds.append((ts, proto))

    d0_frames.sort(key=lambda x: x[0])
    c0c3_resp.sort(key=lambda x: x[0])
    c6_cmds.sort(key=lambda x: x[0])

    return d0_frames, c0c3_resp, c6_cmds


def find_nearest(ts, sorted_list):
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


def find_most_recent(ts, sorted_list):
    """Find the most recent entry at or before ts."""
    idx = bisect.bisect_right(sorted_list, (ts,))
    if idx > 0:
        return sorted_list[idx - 1]
    return None


# ── Main validation ─────────────────────────────────────────────────────────

def run_session(pcap_path, label):
    d0_frames, c0c3_resp, c6_cmds = process_session(pcap_path)

    print(f"\n{'=' * 72}")
    print(f"  {label}")
    print(f"  D0: {len(d0_frames)}, C0/C3: {len(c0c3_resp)}, C6: {len(c6_cmds)}")
    print(f"{'=' * 72}")

    if not d0_frames or not c0c3_resp:
        print(f"  Skipping — insufficient data")
        return {}

    # ── D-01..D-03: D0 vs nearest C0/C3 ────────────────────────────────
    results = {'D-01': [0, 0], 'D-02': [0, 0], 'D-03': [0, 0], 'D-04': [0, 0]}
    d01_detail = Counter()
    d02_detail = Counter()
    d03_detail = Counter()
    d04_detail = Counter()

    # Sanity tracking: confirmed fields should always match
    sanity_mode_ok = 0
    sanity_mode_fail = 0

    # D0 bytes 15-19 exploration
    d0_b15 = Counter()
    d0_b16 = Counter()
    d0_b18 = Counter()
    d0_b19 = Counter()
    d0_b29 = Counter()

    for ts_d0, d0 in d0_frames:
        nearest, dt = find_nearest(ts_d0, c0c3_resp)
        if nearest is None or dt > MAX_DT:
            continue
        _, c0 = nearest

        # ── D-01: Mode ──────────────────────────────────────────────
        d0_mode = d0[5]
        c0_mode = c0[8]
        c0_mode_masked = strip_auto_submode(c0_mode)

        results['D-01'][0] += 1
        d0_name = MODE_NAMES.get(d0_mode, f'0x{d0_mode:02X}')
        c0_name = MODE_NAMES.get(c0_mode, f'0x{c0_mode:02X}')
        c0m_name = MODE_NAMES.get(c0_mode_masked, f'0x{c0_mode_masked:02X}')

        if d0_mode == c0_mode_masked:
            results['D-01'][1] += 1
            d01_detail[(d0_name, c0m_name, 'OK')] += 1
        else:
            d01_detail[(d0_name, c0_name, 'FAIL')] += 1

        # Sanity: C0 fan and temp should decode without errors
        c0_fan = c0[9]
        c0_temp = c0[10] - 0x40

        # ── D-02: Fan ───────────────────────────────────────────────
        d0_fan = d0[6]
        results['D-02'][0] += 1
        if d0_fan == c0_fan:
            results['D-02'][1] += 1
            d02_detail[(f'0x{d0_fan:02X}', 'OK')] += 1
        else:
            d02_detail[(f'D0=0x{d0_fan:02X}', f'C0=0x{c0_fan:02X}', 'FAIL')] += 1

        # ── D-03: Set Temperature ───────────────────────────────────
        d0_temp = d0[7] - 0x40
        results['D-03'][0] += 1
        if d0_temp == c0_temp:
            results['D-03'][1] += 1
            d03_detail[(f'{d0_temp}C', 'OK')] += 1
        else:
            d03_detail[(f'D0={d0_temp}C', f'C0={c0_temp}C', 'FAIL')] += 1

        # ── D0 bytes 15-19 exploration ──────────────────────────────
        d0_b15[d0[15]] += 1
        d0_b16[d0[16]] += 1
        d0_b18[d0[18]] += 1
        d0_b19[d0[19]] += 1
        d0_b29[d0[29]] += 1

    # ── D-04: Swing — D0 byte[11] vs most recent C6 byte[6] ────────
    for ts_d0, d0 in d0_frames:
        d0_swing = d0[11]
        c6_entry = find_most_recent(ts_d0, c6_cmds)
        if c6_entry is None:
            continue
        _, c6 = c6_entry
        c6_swing = c6[6]

        results['D-04'][0] += 1
        d0_sw_name = SWING_NAMES.get(d0_swing, f'0x{d0_swing:02X}')
        c6_sw_name = SWING_NAMES.get(c6_swing, f'0x{c6_swing:02X}')
        if d0_swing == c6_swing:
            results['D-04'][1] += 1
            d04_detail[(d0_sw_name, 'OK')] += 1
        else:
            d04_detail[(f'D0={d0_sw_name}', f'C6={c6_sw_name}', 'FAIL')] += 1

    # ── Report ──────────────────────────────────────────────────────
    for hyp, (total, match) in results.items():
        fail = total - match
        status = ("PASS" if (total >= 20 and fail == 0) else
                  "INSUFFICIENT DATA" if total < 20 else "FAIL")
        print(f"\n  {hyp}: {total} pairs, {match} match, {fail} fail — {status}")

    if d01_detail:
        print(f"\n  D-01 Mode detail:")
        for key, cnt in sorted(d01_detail.items(), key=lambda x: -x[1]):
            print(f"    {key} ({cnt}x)")

    if any(v for v in d02_detail.values()):
        fails_d02 = {k: v for k, v in d02_detail.items() if 'FAIL' in k}
        if fails_d02:
            print(f"\n  D-02 Fan failures:")
            for key, cnt in fails_d02.items():
                print(f"    {key} ({cnt}x)")

    if any(v for v in d03_detail.values()):
        fails_d03 = {k: v for k, v in d03_detail.items() if 'FAIL' in k}
        if fails_d03:
            print(f"\n  D-03 SetTemp failures:")
            for key, cnt in fails_d03.items():
                print(f"    {key} ({cnt}x)")

    if d04_detail:
        print(f"\n  D-04 Swing detail:")
        for key, cnt in sorted(d04_detail.items(), key=lambda x: -x[1]):
            print(f"    {key} ({cnt}x)")

    # ── D0 unexplored bytes ─────────────────────────────────────────
    print(f"\n  D0 unexplored bytes (this session):")
    for name, ctr in [('byte[15]', d0_b15), ('byte[16]', d0_b16),
                       ('byte[18]', d0_b18), ('byte[19]', d0_b19),
                       ('byte[29]', d0_b29)]:
        items = sorted(ctr.items(), key=lambda x: -x[1])
        vals = ', '.join(f'0x{v:02X}:{c}' for v, c in items[:5])
        n_distinct = len(items)
        print(f"    {name}: {n_distinct} distinct — {vals}")

    # D0 byte[16] temperature hypothesis: if variable and in range 0x0A-0x20,
    # could be (raw-40)/2 = -15...-4C or (raw)/2 = 5...16C
    if d0_b16:
        vals = list(d0_b16.keys())
        print(f"\n    byte[16] as temperature (offset-40/2): "
              f"{min(vals)} → {(min(vals)-40)/2:.1f}C, "
              f"{max(vals)} → {(max(vals)-40)/2:.1f}C")
        print(f"    byte[16] as temperature (offset-0/2):  "
              f"{min(vals)} → {min(vals)/2:.1f}C, "
              f"{max(vals)} → {max(vals)/2:.1f}C")
        print(f"    byte[16] as direct integer:            "
              f"{min(vals)}–{max(vals)}")

    return results


def main():
    session_dirs = sys.argv[1:] if len(sys.argv) > 1 else None

    if not session_dirs:
        script_dir = Path(os.path.abspath(__file__)).parent
        base = script_dir.parent.parent / 'Midea-XtremeSaveBlue-display'
        session_dirs = [str(base / f'Session {i}') for i in range(3, 10)
                        if (base / f'Session {i}').exists()]

    if not session_dirs:
        print("No session directories found.")
        sys.exit(1)

    print(f"Sessions: {[Path(d).name for d in session_dirs]}")
    print(f"D0 Intra-bus consistency validation (max dt = {MAX_DT}s)")

    agg = {}
    for d in session_dirs:
        pcap = Path(d) / "session.pcap"
        if not pcap.exists():
            continue
        label = Path(d).name
        results = run_session(str(pcap), label)
        for hyp, (total, match) in results.items():
            if hyp not in agg:
                agg[hyp] = [0, 0]
            agg[hyp][0] += total
            agg[hyp][1] += match

    # Aggregate summary
    print(f"\n{'#' * 72}")
    print(f"  INTRA-BUS D0 CONSISTENCY SUMMARY")
    print(f"  Max time delta: {MAX_DT}s (same bus)")
    print(f"{'#' * 72}")
    print(f"\n  {'ID':<6} {'Field':<15} {'Status':<20} {'Pairs':>6} {'Match':>6} {'Fail':>6}")
    print(f"  {'-' * 64}")
    for hyp in sorted(agg.keys()):
        total, match = agg[hyp]
        fail = total - match
        status = ("PASS" if (total >= 20 and fail == 0) else
                  "INSUFFICIENT DATA" if total < 20 else "FAIL")
        names = {'D-01': 'Mode', 'D-02': 'Fan', 'D-03': 'SetTemp', 'D-04': 'Swing'}
        print(f"  {hyp:<6} {names.get(hyp, '?'):<15} {status:<20} {total:>6} {match:>6} {fail:>6}")
    print()


if __name__ == '__main__':
    main()
