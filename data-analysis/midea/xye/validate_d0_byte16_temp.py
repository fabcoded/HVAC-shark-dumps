#!/usr/bin/env python3
"""
validate_d0_byte16_temp.py — Identify XYE D0 broadcast byte[16] by
cross-validating against ALL available temperature references.

Result: D0 byte[16] = indoor temperature (T1) in direct °C (no formula).
Outdoor temperature hypothesis falsified (mean |Δ|=19.8°C vs confirmed T4).
See protocol_xye.md §6.4, OQ-04.

For each D0 frame, finds the nearest frame of each type within MAX_DT seconds
and compares D0 byte[16] under multiple encoding hypotheses against every
known temperature field.

Reference temperatures:
  XYE C0/C3 response:  T1 byte[11], T2A byte[12], T2B byte[13], T3 byte[14]
  XYE C4/C6 response:  T4 byte[21], Tp byte[22]
  R/T C0 response:     indoor body[11], outdoor body[12]

All XYE sensor temps use (raw-40)/2.  R/T uses (raw-50)/2.

Usage:
    python validate_d0_byte16_temp.py [session_dirs...]
"""

import struct, sys, bisect
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MAX_DT = 3.0

# ── pcap reader ──────────────────────────────────────────────────────────

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


BUS_XYE = 0x00
BUS_RT  = 0x03


# ── Frame extraction ─────────────────────────────────────────────────────

def extract_frames(pcap_path):
    d0_frames = []
    c0c3_resp = []
    c4c6_resp = []
    rt_c0_resp = []

    for ts, pkt_data in read_pcap(pcap_path):
        parsed = parse_hvac_shark(pkt_data)
        if parsed is None:
            continue
        bus_type, proto = parsed

        if bus_type == BUS_XYE and len(proto) == 32 and proto[0] == 0xAA:
            cmd = proto[1]
            if cmd == 0xD0:
                d0_frames.append((ts, proto))
            elif cmd in (0xC0, 0xC3):
                c0c3_resp.append((ts, proto))
            elif cmd in (0xC4, 0xC6):
                c4c6_resp.append((ts, proto))

        elif bus_type == BUS_RT and len(proto) >= 15 and proto[0] == 0x55:
            if len(proto) >= 11:
                msg_type = proto[10]
                if msg_type == 0x03:
                    body = proto[11:]
                    if len(body) >= 13 and body[0] == 0xC0:
                        rt_c0_resp.append((ts, body))

    for lst in (d0_frames, c0c3_resp, c4c6_resp, rt_c0_resp):
        lst.sort(key=lambda x: x[0])

    return d0_frames, c0c3_resp, c4c6_resp, rt_c0_resp


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


# ── Temperature extractors ───────────────────────────────────────────────

def xye_sensor(raw):
    """(raw - 40) / 2 — standard XYE sensor formula."""
    return (raw - 40) / 2.0

def rt_sensor(raw):
    """(raw - 50) / 2 — standard R/T sensor formula."""
    return (raw - 50) / 2.0


# Reference temperature definitions: (name, source_type, extractor)
# source_type: 'c0' = XYE C0/C3, 'c4' = XYE C4/C6, 'rt' = R/T C0
REF_TEMPS = [
    # XYE C0/C3 response
    ('XYE T1 indoor   b[11]', 'c0', lambda p: xye_sensor(p[11])),
    ('XYE T2A coil-in b[12]', 'c0', lambda p: xye_sensor(p[12])),
    ('XYE T2B coil-out b[13]','c0', lambda p: xye_sensor(p[13])),
    ('XYE T3 out-coil b[14]', 'c0', lambda p: xye_sensor(p[14])),
    ('XYE setpoint    b[10]', 'c0', lambda p: float(p[10] - 0x40)),
    # XYE C4/C6 response
    ('XYE T4 outdoor  b[21]', 'c4', lambda p: xye_sensor(p[21])),
    ('XYE Tp discharge b[22]','c4', lambda p: xye_sensor(p[22])),
    ('XYE C4 setpoint b[18]', 'c4', lambda p: float(p[18] - 0x40)),
    # R/T C0 response (body = proto[11:])
    ('R/T indoor    body[11]','rt', lambda b: rt_sensor(b[11])),
    ('R/T outdoor   body[12]','rt', lambda b: rt_sensor(b[12])),
]

# Candidate encodings for D0 byte[16]
ENCODINGS = [
    ('direct',     lambda r: float(r)),
    ('(r-40)/2',   lambda r: (r - 40) / 2.0),
    ('(r-50)/2',   lambda r: (r - 50) / 2.0),
    ('r/2',        lambda r: r / 2.0),
    ('r*2',        lambda r: float(r * 2)),
    ('r+10',       lambda r: float(r + 10)),
    ('r-10',       lambda r: float(r - 10)),
]


# ── Main ─────────────────────────────────────────────────────────────────

def process_session(pcap_path, label):
    d0_frames, c0c3_resp, c4c6_resp, rt_c0_resp = extract_frames(pcap_path)

    print(f"\n{'=' * 78}")
    print(f"  {label}")
    print(f"  D0: {len(d0_frames)}, C0/C3: {len(c0c3_resp)}, "
          f"C4/C6: {len(c4c6_resp)}, R/T C0: {len(rt_c0_resp)}")
    print(f"{'=' * 78}")

    if not d0_frames:
        print("  No D0 frames — skipping")
        return None

    # Raw distribution
    d0_b16_dist = Counter(d0[16] for _, d0 in d0_frames)
    print(f"  D0 byte[16] raw: ", end='')
    for val, cnt in sorted(d0_b16_dist.items()):
        print(f"0x{val:02X}({val})×{cnt}  ", end='')
    print()

    # Also show byte[18] and byte[7] for context
    d0_b18_dist = Counter(d0[18] for _, d0 in d0_frames)
    d0_b7_dist = Counter(d0[7] for _, d0 in d0_frames)
    print(f"  D0 byte[18] raw: ", end='')
    for val, cnt in sorted(d0_b18_dist.items()):
        print(f"0x{val:02X}({val})×{cnt}  ", end='')
    print()

    # For each source type, build lookup
    sources = {
        'c0': c0c3_resp,
        'c4': c4c6_resp,
        'rt': rt_c0_resp,
    }

    # Collect comparison data: for each D0 frame, get all ref temps
    rows = []
    for ts_d0, d0 in d0_frames:
        row = {'ts': ts_d0, 'b16': d0[16], 'b18': d0[18], 'b7': d0[7]}
        for ref_name, src_type, extractor in REF_TEMPS:
            nearest, dt = find_nearest(ts_d0, sources[src_type])
            if nearest is not None and dt <= MAX_DT:
                _, frame = nearest
                try:
                    val = extractor(frame)
                    # Skip clearly invalid values (0xFF raw = unavailable)
                    if src_type == 'rt':
                        raw = frame[12] if 'outdoor' in ref_name else frame[11]
                        if raw == 0xFF:
                            continue
                    row[ref_name] = val
                except (IndexError, ValueError):
                    pass
            # else: no match within window
        rows.append(row)

    if not rows:
        print("  No matched rows")
        return None

    # ── Summary table: mean absolute difference for each (encoding, ref) ──
    print(f"\n  Mean absolute difference: D0 byte[16] (encoded) vs reference temp")
    print(f"  {len(rows)} D0 frames matched\n")

    # Header
    enc_names = [e[0] for e in ENCODINGS]
    hdr = f"  {'Reference':<28s}"
    for en in enc_names:
        hdr += f"  {en:>9s}"
    hdr += f"  {'N':>5s}"
    print(hdr)
    print(f"  {'-'*28}" + f"  {'-'*9}" * len(enc_names) + f"  {'-'*5}")

    best_overall = (999.0, '', '')

    for ref_name, _, _ in REF_TEMPS:
        valid = [(r['b16'], r[ref_name]) for r in rows if ref_name in r]
        if not valid:
            line = f"  {ref_name:<28s}"
            for _ in ENCODINGS:
                line += f"  {'—':>9s}"
            line += f"  {0:>5d}"
            print(line)
            continue

        line = f"  {ref_name:<28s}"
        for enc_name, enc_fn in ENCODINGS:
            diffs = [abs(enc_fn(raw) - ref) for raw, ref in valid]
            mean_abs = sum(diffs) / len(diffs)
            if mean_abs < best_overall[0]:
                best_overall = (mean_abs, enc_name, ref_name)
            # Color-code: mark good matches
            marker = ''
            if mean_abs < 0.5:
                marker = ' **'
            elif mean_abs < 1.0:
                marker = ' * '
            elif mean_abs < 2.0:
                marker = ' ~ '
            line += f"  {mean_abs:8.2f}{marker[0] if marker else ' '}"
        line += f"  {len(valid):>5d}"
        print(line)

    print(f"\n  Best match: {best_overall[1]} vs {best_overall[2]} "
          f"(mean |Δ| = {best_overall[0]:.2f}°C)")

    # ── Detailed view for the best match ─────────────────────────────────
    best_enc_name, best_ref_name = best_overall[1], best_overall[2]
    best_enc_fn = dict(ENCODINGS)[best_enc_name]

    valid = [(r['ts'], r['b16'], r[best_ref_name])
             for r in rows if best_ref_name in r]

    if valid:
        diffs = [best_enc_fn(raw) - ref for _, raw, ref in valid]
        within_05 = sum(1 for d in diffs if abs(d) < 0.5)
        within_1  = sum(1 for d in diffs if abs(d) < 1.0)
        within_2  = sum(1 for d in diffs if abs(d) < 2.0)
        max_abs = max(abs(d) for d in diffs)
        mean_d = sum(diffs) / len(diffs)
        print(f"  Details: {best_enc_name}(D0[16]) vs {best_ref_name}")
        print(f"    N={len(valid)}, mean Δ={mean_d:+.2f}, max |Δ|={max_abs:.2f}")
        print(f"    within ±0.5°C: {within_05}/{len(valid)} ({100*within_05/len(valid):.1f}%)")
        print(f"    within ±1.0°C: {within_1}/{len(valid)} ({100*within_1/len(valid):.1f}%)")
        print(f"    within ±2.0°C: {within_2}/{len(valid)} ({100*within_2/len(valid):.1f}%)")

    # ── Show all ref temps side-by-side for first 5 D0 frames ────────────
    print(f"\n  Sample D0 frames with all reference temps (first 5):")
    print(f"  {'b16':>4s}  {'b18':>4s}  ", end='')
    for ref_name, _, _ in REF_TEMPS:
        short = ref_name.split()[-1] if '/' not in ref_name.split()[-1] else ref_name.split()[0] + ref_name.split()[-1]
        print(f"  {ref_name[:14]:>14s}", end='')
    print()

    for row in rows[:5]:
        print(f"  {row['b16']:4d}  {row['b18']:4d}  ", end='')
        for ref_name, _, _ in REF_TEMPS:
            if ref_name in row:
                print(f"  {row[ref_name]:14.1f}", end='')
            else:
                print(f"  {'—':>14s}", end='')
        print()

    return rows


def main():
    if len(sys.argv) > 1:
        session_dirs = sys.argv[1:]
    else:
        base = Path(r"c:\Users\fabia\OneDrive\Elektronik und Basteln\HVAC and Heat"
                     r"\HVAC Shark DEV\HVAC-shark-dumps"
                     r"\Midea-XtremeSaveBlue-logicanalyzer")
        session_dirs = []
        for i in range(3, 14):
            d = base / f"Session {i}"
            if d.exists():
                session_dirs.append(str(d))

    all_rows = []
    for sd in session_dirs:
        p = Path(sd)
        pcap = p / "session.pcap"
        if not pcap.exists():
            continue
        result = process_session(str(pcap), p.name)
        if result:
            all_rows.extend(result)

    # ── Global summary ────────────────────────────────────────────────
    if not all_rows:
        return

    print(f"\n{'=' * 78}")
    print(f"  GLOBAL SUMMARY — {len(all_rows)} D0 frames across all sessions")
    print(f"{'=' * 78}")

    enc_names = [e[0] for e in ENCODINGS]
    hdr = f"  {'Reference':<28s}"
    for en in enc_names:
        hdr += f"  {en:>9s}"
    hdr += f"  {'N':>5s}"
    print(hdr)
    print(f"  {'-'*28}" + f"  {'-'*9}" * len(enc_names) + f"  {'-'*5}")

    best_overall = (999.0, '', '')

    for ref_name, _, _ in REF_TEMPS:
        valid = [(r['b16'], r[ref_name]) for r in all_rows if ref_name in r]
        if not valid:
            line = f"  {ref_name:<28s}"
            for _ in ENCODINGS:
                line += f"  {'—':>9s}"
            line += f"  {0:>5d}"
            print(line)
            continue

        line = f"  {ref_name:<28s}"
        for enc_name, enc_fn in ENCODINGS:
            diffs = [abs(enc_fn(raw) - ref) for raw, ref in valid]
            mean_abs = sum(diffs) / len(diffs)
            if mean_abs < best_overall[0]:
                best_overall = (mean_abs, enc_name, ref_name)
            marker = ''
            if mean_abs < 0.5:
                marker = '**'
            elif mean_abs < 1.0:
                marker = '* '
            elif mean_abs < 2.0:
                marker = '~ '
            line += f"  {mean_abs:7.2f}{marker if marker else '  '}"
        line += f"  {len(valid):>5d}"
        print(line)

    print(f"\n  BEST MATCH: {best_overall[1]} vs {best_overall[2]} "
          f"(mean |Δ| = {best_overall[0]:.2f}°C)")

    # Detailed stats for best
    best_enc_fn = dict(ENCODINGS)[best_overall[1]]
    valid = [(r['b16'], r[best_overall[2]]) for r in all_rows if best_overall[2] in r]
    if valid:
        diffs = [best_enc_fn(raw) - ref for raw, ref in valid]
        within_05 = sum(1 for d in diffs if abs(d) < 0.5)
        within_1  = sum(1 for d in diffs if abs(d) < 1.0)
        within_2  = sum(1 for d in diffs if abs(d) < 2.0)
        max_abs = max(abs(d) for d in diffs)
        mean_d = sum(diffs) / len(diffs)
        std_d = (sum((d - mean_d)**2 for d in diffs) / len(diffs)) ** 0.5
        print(f"    N={len(valid)}, mean Δ={mean_d:+.3f}, std={std_d:.3f}, max |Δ|={max_abs:.2f}")
        print(f"    within ±0.5°C: {within_05}/{len(valid)} ({100*within_05/len(valid):.1f}%)")
        print(f"    within ±1.0°C: {within_1}/{len(valid)} ({100*within_1/len(valid):.1f}%)")
        print(f"    within ±2.0°C: {within_2}/{len(valid)} ({100*within_2/len(valid):.1f}%)")

    # ── Per-session best match view ──────────────────────────────────
    print(f"\n  Per-session best-match breakdown:")
    print(f"  {'Session':<12s}  {'D0 b16 vals':<20s}  {'Best ref (global enc)':<28s}  "
          f"{'mean Δ':>8s}  {'max|Δ|':>8s}  {'N':>5s}")

    # Re-process per session
    for sd in session_dirs:
        p = Path(sd)
        pcap = p / "session.pcap"
        if not pcap.exists():
            continue
        sess_rows = [r for r in all_rows if True]  # need per-session...

    # Actually just re-derive from raw D0 dist per session
    # (simpler: just print the raw values per session from the output above)


if __name__ == '__main__':
    main()
