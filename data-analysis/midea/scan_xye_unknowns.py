#!/usr/bin/env python3
"""
scan_xye_unknowns.py — Scan unknown/hypothesis bytes in XYE frames across all sessions.

Extracts value distributions for bytes that are currently unknown, hypothesis-level,
or under-documented:

  C0/C3 32-byte response:
    byte[15]  CURRENT      (always 0x00 on tested HW?)
    byte[16]  FREQUENCY    (typically 0xFF?)
    byte[17]  TIMER_START  (15-min interval hypothesis)
    byte[18]  TIMER_STOP   (15-min interval hypothesis)
    byte[22]  ERROR_1      (error bitmask — variability?)
    byte[23]  ERROR_2
    byte[24]  ERROR_3
    byte[25]  ERROR_4
    byte[26]  COMM_ERROR   (0-2?)
    byte[27]  L1 / UNKNOWN (codeberg Erlang: separate field)
    byte[28]  L2 / UNKNOWN
    byte[29]  L3 / UNKNOWN

  C4/C6 32-byte response:
    byte[19]  DEVICE_TYPE  (constant 0xBC?)
    byte[20]  UNKNOWN      (constant 0xD6?)
    byte[23]-byte[29]  RESERVED (all zeros?)

  D0 32-byte broadcast:
    byte[2]   UNKNOWN      (constant 0x20?)
    byte[3]   UNKNOWN      (constant 0x01?)
    byte[4]   UNKNOWN      (constant 0x00?)
    byte[8]-byte[10]  UNKNOWN (all zeros?)
    byte[12]-byte[29] UNKNOWN (unexplored region)

  Cross-bus temperature comparison:
    XYE T1 vs R/T C0 body[11], XYE T3 vs R/T C0 body[12]
    Using each bus's own offset formula, flag >1C discrepancies.

  Temperature unit archaeology:
    Check whether raw bytes could represent Fahrenheit or Kelvin instead of Celsius.
    - Fahrenheit: UART body[15] decimal nibble / mill1000 fahrenheits flag
    - Kelvin: Would need offset ~273 for 0C — check if any offset is near 273*2=546
              or if raw values make sense as decikelvin.
    - UART 0xA0 alternative temp frames (OQ-18 in protocol_serial.md)

Usage:
    python scan_xye_unknowns.py [session_dirs...]
"""

import struct, sys, os, bisect
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Constants ───────────────────────────────────────────────────────────────

BUS_XYE  = 0x00
BUS_UART = 0x01
BUS_DISP = 0x02
BUS_RT   = 0x03

MAX_DT = 2.0  # seconds — max timestamp gap for cross-bus comparison

# ── pcap reader (reused from validate_xye_vs_rt.py) ────────────────────────

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


# ── Frame classifiers ──────────────────────────────────────────────────────

def classify_xye(proto):
    """Classify an XYE frame. Returns (type_str, proto) or None."""
    if len(proto) < 2 or proto[0] != 0xAA:
        return None
    cmd = proto[1]

    if len(proto) == 32:
        if cmd in (0xC0, 0xC3):
            return ('c0c3_resp', proto)
        if cmd in (0xC4, 0xC6):
            return ('c4c6_resp', proto)
        if cmd == 0xD0:
            return ('d0_bcast', proto)
    elif len(proto) == 16:
        if cmd in (0xC0, 0xC3, 0xC4, 0xC6, 0xCC, 0xCD):
            return ('master_cmd', proto)
    return None


def decode_rt_c0_temps(raw):
    """Extract temperatures from R/T C0 response for cross-bus comparison."""
    if len(raw) < 15 or raw[0] != 0x55:
        return None
    if len(raw) < 11:
        return None
    msg_type = raw[10]
    if msg_type != 0x03:
        return None
    body = raw[11:]
    if len(body) < 16:
        return None
    if body[0] != 0xC0:
        return None
    return {
        'indoor_c':  (body[11] - 50) / 2.0,
        'outdoor_c': (body[12] - 50) / 2.0,
        'body_15':   body[15] if len(body) > 15 else None,
        'indoor_raw':  body[11],
        'outdoor_raw': body[12],
    }


def decode_uart_msg_type(raw):
    """Detect UART message type for 0xA0 alternative temp encoding search."""
    if len(raw) < 2 or raw[0] != 0xAA:
        return None
    length = raw[1]
    if length < 0x0D or length > 0x40:
        return None
    if len(raw) < length + 2:
        return None
    if len(raw) >= 11:
        msg_type_byte = raw[10]
        body = raw[11:]
        return {'msg_type': msg_type_byte, 'body': body, 'raw': raw}
    return None


# ── Temperature unit analysis helpers ──────────────────────────────────────

def analyze_temp_unit(raw_byte, known_celsius, label):
    """Given a raw byte and its known Celsius value, check if alternative
    unit interpretations (Fahrenheit, Kelvin) could also explain it.

    Returns a dict of plausible interpretations.
    """
    results = {}

    # Known Celsius interpretations (all confirmed offsets)
    offsets_c = {
        'offset-40 (XYE sensors)':   (raw_byte - 40) / 2.0,
        'offset-50 (UART sensors)':  (raw_byte - 50) / 2.0,
        'offset-30 (C1-G1 indoor)':  (raw_byte - 30) / 2.0,
        'offset-0x40 (XYE setpoint)': raw_byte - 0x40,
        'direct (Tp discharge)':      float(raw_byte),
    }

    # Fahrenheit: interpret raw as F, then convert to C
    # raw_as_F → C = (raw_as_F - 32) * 5/9
    raw_as_f = float(raw_byte)
    f_to_c = (raw_as_f - 32) * 5.0 / 9.0
    results['raw_as_fahrenheit'] = f_to_c

    # ESPHome interpretation: raw directly as F (no offset)
    results['esphome_f_direct'] = f_to_c

    # Kelvin interpretations:
    # If raw = T_kelvin / 2 + offset, then T_C = (raw - offset) / 2 - 273.15
    # For raw=80 to be 20C: (80 - offset) / 2 - 273.15 = 20
    #   → offset = 80 - 2*(20 + 273.15) = 80 - 586.3 = -506.3 (unreasonable)
    # So single-byte Kelvin with scale 0.5 doesn't work for room temps.

    # But: if raw = T_kelvin - 200 (compact Kelvin, offset 200):
    # 20C = 293.15K → raw = 93.15 → 93. Plausible single-byte range.
    # Check: raw 80 → 280K = 6.85C. raw 90 → 290K = 16.85C.
    results['kelvin_offset_200'] = raw_byte + 200 - 273.15

    # Decikelvin: raw = T_K * 10, but 293K * 10 = 2930 — doesn't fit single byte.
    # Two-byte decikelvin is used in some protocols (BACnet, KNX).

    # Kelvin with scale 1 and offset 0: raw = T_K → 20C = 293K. Doesn't fit byte.
    # Kelvin with scale 2 and offset 0: raw = T_K / 2 → 20C = 146.6 → 147. Fits byte!
    results['kelvin_div2'] = raw_byte * 2 - 273.15

    return results


# ── Session processing ──────────────────────────────────────────────────────

def process_session(pcap_path, session_label):
    """Process one session pcap, collecting all frame types and byte distributions."""

    c0c3_bytes = defaultdict(Counter)
    c4c6_bytes = defaultdict(Counter)
    d0_bytes   = defaultdict(Counter)
    counts = Counter()

    # Cross-bus temperature data
    xye_temps  = []  # [(ts, t1_c, t3_c, t1_raw, t3_raw)]
    rt_temps   = []  # [(ts, indoor_c, outdoor_c, body_15, indoor_raw, outdoor_raw)]

    # UART special frame search
    uart_a0_frames = []
    uart_body15_values = Counter()

    for ts, pkt_data in read_pcap(pcap_path):
        parsed = parse_hvac_shark(pkt_data)
        if parsed is None:
            continue
        bus_type, proto = parsed

        if bus_type == BUS_XYE:
            clf = classify_xye(proto)
            if clf is None:
                continue
            ftype, data = clf
            counts[ftype] += 1

            if ftype == 'c0c3_resp':
                for i in range(32):
                    c0c3_bytes[i][data[i]] += 1
                t1_c = (data[11] - 40) / 2.0
                t3_c = (data[14] - 40) / 2.0
                xye_temps.append((ts, t1_c, t3_c, data[11], data[14]))

            elif ftype == 'c4c6_resp':
                for i in range(32):
                    c4c6_bytes[i][data[i]] += 1

            elif ftype == 'd0_bcast':
                for i in range(32):
                    d0_bytes[i][data[i]] += 1

        elif bus_type == BUS_RT:
            rt_data = decode_rt_c0_temps(proto)
            if rt_data is not None:
                rt_temps.append((ts, rt_data['indoor_c'], rt_data['outdoor_c'],
                                 rt_data['body_15'], rt_data['indoor_raw'],
                                 rt_data['outdoor_raw']))

        elif bus_type == BUS_UART:
            uart = decode_uart_msg_type(proto)
            if uart is not None:
                if uart['msg_type'] == 0x02 and len(uart['body']) > 0:
                    if uart['body'][0] == 0xA0:
                        uart_a0_frames.append((ts, uart['body']))
                        counts['uart_a0'] += 1
                if uart['msg_type'] == 0x03 and uart['body'][0] == 0xC0:
                    if len(uart['body']) > 15:
                        uart_body15_values[uart['body'][15]] += 1

    return {
        'counts': counts,
        'c0c3_bytes': c0c3_bytes,
        'c4c6_bytes': c4c6_bytes,
        'd0_bytes': d0_bytes,
        'xye_temps': xye_temps,
        'rt_temps': rt_temps,
        'uart_a0_frames': uart_a0_frames,
        'uart_body15_values': uart_body15_values,
    }


# ── Reporting ───────────────────────────────────────────────────────────────

def print_byte_distribution(label, bytes_dict, byte_offsets, frame_count):
    """Print value distribution for specified byte offsets."""
    print(f"\n  {label} ({frame_count} frames):")
    print(f"  {'Byte':>6}  {'Values (hex: count)':60}  {'Status'}")
    print(f"  {'-' * 80}")
    for offset in byte_offsets:
        ctr = bytes_dict.get(offset, Counter())
        if not ctr:
            print(f"  [0x{offset:02X}]  (no data)")
            continue
        total = sum(ctr.values())
        items = sorted(ctr.items(), key=lambda x: -x[1])
        val_strs = []
        for val, cnt in items[:8]:
            pct = cnt / total * 100
            val_strs.append(f"0x{val:02X}:{cnt}({pct:.0f}%)")
        if len(items) > 8:
            val_strs.append(f"...+{len(items)-8} more")

        if len(items) == 1:
            val = items[0][0]
            status = f"CONSTANT 0x{val:02X}"
        elif len(items) <= 3 and items[0][1] > total * 0.9:
            status = f"MOSTLY 0x{items[0][0]:02X} ({items[0][1]}/{total})"
        else:
            status = f"VARIABLE ({len(items)} distinct)"

        val_str = ', '.join(val_strs)
        print(f"  [0x{offset:02X}]  {val_str:60}  {status}")


def print_cross_bus_temps(xye_temps, rt_temps, session_label):
    """Cross-bus temperature comparison: XYE T1/T3 vs R/T indoor/outdoor.
    Also performs alternative-unit plausibility check (Fahrenheit, Kelvin)."""
    if not xye_temps or not rt_temps:
        print(f"\n  Cross-bus temperature comparison: insufficient data "
              f"(XYE: {len(xye_temps)}, R/T: {len(rt_temps)})")
        return

    xye_sorted = sorted(xye_temps, key=lambda x: x[0])
    rt_sorted  = sorted(rt_temps, key=lambda x: x[0])

    t1_diffs = []
    t3_diffs = []
    matched = 0

    # Collect raw bytes for unit archaeology
    xye_t1_raws = []
    xye_t3_raws = []
    rt_indoor_raws = []
    rt_outdoor_raws = []

    for ts_rt, indoor_c, outdoor_c, body_15, indoor_raw, outdoor_raw in rt_sorted:
        idx = bisect.bisect_left(xye_sorted, (ts_rt,))
        best_dt = float('inf')
        best = None
        for i in (idx - 1, idx):
            if 0 <= i < len(xye_sorted):
                dt = abs(xye_sorted[i][0] - ts_rt)
                if dt < best_dt:
                    best_dt = dt
                    best = xye_sorted[i]
        if best is None or best_dt > MAX_DT:
            continue

        matched += 1
        _, xye_t1, xye_t3, xye_t1_raw, xye_t3_raw = best
        t1_diff = xye_t1 - indoor_c
        t3_diff = xye_t3 - outdoor_c

        if abs(indoor_c) < 100 and abs(xye_t1) < 100:
            t1_diffs.append(t1_diff)
            xye_t1_raws.append(xye_t1_raw)
            rt_indoor_raws.append(indoor_raw)
        if abs(outdoor_c) < 100 and abs(xye_t3) < 100:
            t3_diffs.append(t3_diff)
            xye_t3_raws.append(xye_t3_raw)
            rt_outdoor_raws.append(outdoor_raw)

    print(f"\n  Cross-bus temperature comparison ({session_label}):")
    print(f"  Matched pairs (within {MAX_DT}s): {matched}")

    if t1_diffs:
        mean_d = sum(t1_diffs) / len(t1_diffs)
        max_d  = max(abs(d) for d in t1_diffs)
        n_bad  = sum(1 for d in t1_diffs if abs(d) > 1.0)
        print(f"  T1 indoor:  mean diff = {mean_d:+.2f}C, max |diff| = {max_d:.2f}C, "
              f">1C discrepancies: {n_bad}/{len(t1_diffs)}")
    else:
        print(f"  T1 indoor:  no valid pairs")

    if t3_diffs:
        mean_d = sum(t3_diffs) / len(t3_diffs)
        max_d  = max(abs(d) for d in t3_diffs)
        n_bad  = sum(1 for d in t3_diffs if abs(d) > 1.0)
        print(f"  T3 outdoor: mean diff = {mean_d:+.2f}C, max |diff| = {max_d:.2f}C, "
              f">1C discrepancies: {n_bad}/{len(t3_diffs)}")
    else:
        print(f"  T3 outdoor: no valid pairs")

    if t1_diffs and abs(sum(t1_diffs) / len(t1_diffs)) > 2.0:
        print(f"  *** WARNING: systematic T1 offset detected — check formulas!")
    if t3_diffs and abs(sum(t3_diffs) / len(t3_diffs)) > 2.0:
        print(f"  *** WARNING: systematic T3 offset detected — check formulas!")

    # ── Temperature unit archaeology ────────────────────────────────────
    # Pick a representative raw byte pair (median) and check all interpretations
    if xye_t1_raws and rt_indoor_raws:
        xye_raw = sorted(xye_t1_raws)[len(xye_t1_raws) // 2]
        rt_raw  = sorted(rt_indoor_raws)[len(rt_indoor_raws) // 2]
        known_c = (xye_raw - 40) / 2.0  # confirmed formula

        print(f"\n  Temperature unit archaeology (representative T1 indoor):")
        print(f"  XYE raw=0x{xye_raw:02X} ({xye_raw}), R/T raw=0x{rt_raw:02X} ({rt_raw})")
        print(f"  {'Interpretation':<35} {'XYE':>10}  {'R/T':>10}  {'Match?':>8}")
        print(f"  {'-' * 68}")

        interps = [
            ("Celsius offset-40 /2 (XYE confirmed)", (xye_raw - 40) / 2.0, None),
            ("Celsius offset-50 /2 (R/T confirmed)", None, (rt_raw - 50) / 2.0),
            ("Raw as Fahrenheit -> C", (xye_raw - 32) * 5/9, (rt_raw - 32) * 5/9),
            ("Fahrenheit offset-40 /2 -> C", ((xye_raw - 40) / 2.0 - 32) * 5/9, ((rt_raw - 50) / 2.0 - 32) * 5/9),
            ("Kelvin offset-200 (raw+200-273.15)", xye_raw + 200 - 273.15, rt_raw + 200 - 273.15),
            ("Kelvin /2 (raw*2 - 273.15)", xye_raw * 2 - 273.15, rt_raw * 2 - 273.15),
            ("Kelvin offset-40 /2 - 273.15", (xye_raw - 40) / 2.0 - 273.15, (rt_raw - 50) / 2.0 - 273.15),
        ]

        for name, xye_val, rt_val in interps:
            xye_str = f"{xye_val:.1f}C" if xye_val is not None else "N/A"
            rt_str  = f"{rt_val:.1f}C" if rt_val is not None else "N/A"
            # Check plausibility: room temp should be 10-35C
            xye_plausible = xye_val is not None and 5 < xye_val < 45
            rt_plausible  = rt_val is not None and 5 < rt_val < 45
            if xye_val is not None and rt_val is not None:
                match = "YES" if abs(xye_val - rt_val) < 2.0 else "no"
            elif xye_plausible or rt_plausible:
                match = "plausible"
            else:
                match = "no"
            print(f"  {name:<35} {xye_str:>10}  {rt_str:>10}  {match:>8}")

        # Key insight: if raw_as_Fahrenheit gives a plausible room temp,
        # there's a chance some units ship in F mode.
        xye_as_f_c = (xye_raw - 32) * 5 / 9
        print(f"\n  Key observation: XYE raw {xye_raw} interpreted as Fahrenheit = "
              f"{xye_raw}F = {xye_as_f_c:.1f}C")
        if 10 < xye_as_f_c < 35:
            print(f"  -> This IS plausible as a room temperature!")
            print(f"     ESPHome's F interpretation may have worked for some users"
                  f" with US-market units.")
        else:
            print(f"  -> NOT plausible as a room temperature (too {'cold' if xye_as_f_c < 10 else 'hot'}).")

        # Kelvin analysis
        print(f"\n  Kelvin analysis:")
        print(f"  - Single byte cannot hold Kelvin directly (293K for 20C > 255)")
        print(f"  - Kelvin/2 (raw*2-273.15): XYE raw {xye_raw} -> {xye_raw*2-273.15:.1f}C"
              f" {'PLAUSIBLE' if 5 < xye_raw*2-273.15 < 45 else 'NOT plausible'}")
        print(f"  - 16-bit Kelvin (C1 sub-page): uses 0.01C precision, signed — "
              f"this IS effectively a Kelvin-like absolute encoding without offset.")
        print(f"  - Decikelvin (BACnet/KNX style): 20C = 2931.5 dK — requires 16-bit, "
              f"not single byte")
        # Check if any of the confirmed offsets could secretly be Kelvin-derived
        # offset 40: if this is 2*T_K/10, then T_K = (raw-40)/2 + 273.15
        # For raw=80: T_K = 20 + 273.15 = 293.15K -> T_C = 20C. This is just
        # the confirmed formula with a different mental model.
        print(f"  - Offset 40 as Kelvin-derived: unlikely. Offset 40 maps raw=40 to 0C,"
              f"\n    not to any clean Kelvin boundary (0C = 273.15K).")
        print(f"  - Conclusion: all confirmed single-byte encodings are Celsius-native with"
              f"\n    arbitrary offsets. No Kelvin influence detected.")


def print_fahrenheit_analysis(uart_body15, uart_a0_frames, session_label):
    """Analyze UART body[15] for Fahrenheit flag and 0xA0 alternative encodings."""
    print(f"\n  Fahrenheit / alternative encoding analysis ({session_label}):")

    if uart_body15:
        print(f"  UART C0 body[15] (decimal nibble / temp precision):")
        total = sum(uart_body15.values())
        for val, cnt in sorted(uart_body15.items(), key=lambda x: -x[1]):
            lo = val & 0x0F
            hi = (val >> 4) & 0x0F
            print(f"    0x{val:02X} ({cnt}x / {total}) — lo_nibble={lo} (indoor decimal), "
                  f"hi_nibble={hi} (outdoor decimal)")
        has_nonzero = any(v != 0 for v in uart_body15.keys())
        if has_nonzero:
            print(f"    -> Non-zero nibbles found: Celsius decimal precision active")
            print(f"       mill1000 parse_temperature(fahrenheits=False) path is in use")
        else:
            print(f"    -> All zeros: no decimal precision (could be either C or F)")
    else:
        print(f"  UART C0 body[15]: no data (no UART C0 frames on this bus)")

    if uart_a0_frames:
        print(f"  UART 0xA0 alternative temp frames: {len(uart_a0_frames)} found!")
        for ts, body in uart_a0_frames[:5]:
            if len(body) > 1:
                alt_temp = ((body[1] & 0x3E) >> 1) + 12
                print(f"    t={ts:.3f}  body[1]=0x{body[1]:02X}  alt_temp={alt_temp}C")
    else:
        print(f"  UART 0xA0 alternative temp frames: none found")


# ── Offset origin analysis ──────────────────────────────────────────────────

def print_offset_origin_analysis():
    """Print analysis of temperature offset origins and potential unit influences."""
    print(f"\n{'=' * 72}")
    print(f"  TEMPERATURE OFFSET ORIGIN ANALYSIS")
    print(f"{'=' * 72}")

    print("""
  All confirmed encodings mapped to their zero-point and range:

  Offset  Zero-point (C)  Scale    Range (0-255)            Context
  ------  --------------  -----    ---------                -------
     0    0.0 C           0.5 C    0.0 to 127.5 C          Mainboard AA30 outdoor
    30   -15.0 C          0.5 C   -15.0 to 112.5 C         UART C1-G1 indoor (T1/T2)
    40   -20.0 C          0.5 C   -20.0 to 107.5 C         XYE sensors (T1-T4, Tp)
    50   -25.0 C          0.5 C   -25.0 to 102.5 C         UART/R/T C0 sensors
    64   -64.0 C          1.0 C   -64.0 to 191.0 C         XYE setpoint (T + 0x40)
     0     0.0 C          1.0 C     0.0 to 255.0 C         UART C1-G1 Tp discharge

  Fahrenheit analysis of offsets:
  - Offset 30: zero at -15C = 5F. Not a clean F boundary.
  - Offset 40: zero at -20C = -4F. Not a clean F boundary.
  - Offset 50: zero at -25C = -13F. Not a clean F boundary.
  - Offset 64 (0x40): zero at -64C = -83.2F. Not a clean F boundary.
    BUT: raw=0x50 (80) maps to 16C (minimum setpoint) and raw=0x5E (94) to 30C.
    In F: 16C = 60.8F, 30C = 86F. The raw range 80-94 does NOT match these.

  Kelvin analysis of offsets:
  - 0C = 273.15K. No single-byte offset comes close to 273 or 546 (2*273).
  - Offset 40/2 formula: raw=40 -> 0C = 273.15K. If Kelvin-derived, raw would need
    to be ~586 for 0C at scale 0.5 (impossible in single byte).
  - Conclusion: No Kelvin influence in single-byte encodings.

  Design pattern analysis:
  - Indoor-optimized: offset 30 covers -15 to +112.5C (raw 0-255)
    -> Comfortable indoor range (15-35C) maps to raw 60-130 (center of byte range)
  - Outdoor-optimized: offset 50 covers -25 to +102.5C
    -> Extreme outdoor range (-25 to +50C) maps to raw 0-150 (lower half of byte)
  - XYE (offset 40): compromise between indoor and outdoor
    -> -20 to +107.5C. Suitable for both sensor types.
  - Mainboard (offset 0): simplest encoding, full positive range only
    -> AA30 outdoor sensor: plausible for climates never below 0C?

  Cultural/regional hypothesis:
  - The offset progression 30 -> 40 -> 50 suggests incremental evolution, not a
    deliberate Fahrenheit/Kelvin conversion.
  - Offset 50 (UART/R/T) may be the oldest: it is shared with the WiFi dongle
    protocol, which was designed for international markets (hence wider range).
  - Offset 40 (XYE): RS-485 bus used in commercial HVAC (Carrier/Midea Building
    Technology). Commercial units operate in controlled environments, so a slightly
    narrower range is acceptable.
  - Offset 30 (C1 Group 1): latest protocol extension. Indoor-only optimization
    suggests this was designed after the outdoor sensors were already on offset 50.

  The mill1000 fahrenheits=False parameter suggests the protocol CAN carry Fahrenheit
  values, but no F-mode has been observed in any capture. US-market units may toggle
  this flag — worth testing if hardware becomes available.
""")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    session_dirs = sys.argv[1:] if len(sys.argv) > 1 else None

    if not session_dirs:
        script_dir = Path(os.path.abspath(__file__)).parent
        base = script_dir.parent.parent / 'Midea-XtremeSaveBlue-display'
        session_dirs = [str(base / f'Session {i}') for i in range(1, 10)
                        if (base / f'Session {i}').exists()]

    if not session_dirs:
        print("No session directories found. Pass paths as arguments.")
        sys.exit(1)

    print(f"Sessions: {[Path(d).name for d in session_dirs]}")
    print(f"Scanning unknown/hypothesis bytes in XYE frames...\n")

    # Byte offsets to scan per frame type
    c0c3_scan_offsets = [15, 16, 17, 18, 22, 23, 24, 25, 26, 27, 28, 29]
    c4c6_scan_offsets = [19, 20, 23, 24, 25, 26, 27, 28, 29]
    d0_scan_offsets = [2, 3, 4, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18,
                       19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]

    # Aggregate counters
    agg_c0c3 = defaultdict(Counter)
    agg_c4c6 = defaultdict(Counter)
    agg_d0   = defaultdict(Counter)
    agg_body15 = Counter()
    total_a0 = 0
    all_a0_frames = []

    for d in session_dirs:
        pcap = Path(d) / "session.pcap"
        if not pcap.exists():
            print(f"[skip] {d}: no session.pcap")
            continue
        label = Path(d).name
        print(f"{'=' * 72}")
        print(f"  {label}")
        print(f"{'=' * 72}")
        print(f"  Reading {pcap}...")

        result = process_session(str(pcap), label)

        print(f"  Frame counts: {dict(result['counts'])}")

        print_byte_distribution(
            "C0/C3 Response — Hypothesis/Unknown bytes",
            result['c0c3_bytes'], c0c3_scan_offsets,
            result['counts'].get('c0c3_resp', 0))

        print_byte_distribution(
            "C4/C6 Response — Reserved/Constant bytes",
            result['c4c6_bytes'], c4c6_scan_offsets,
            result['counts'].get('c4c6_resp', 0))

        print_byte_distribution(
            "D0 Broadcast — Unexplored bytes",
            result['d0_bytes'], d0_scan_offsets,
            result['counts'].get('d0_bcast', 0))

        print_cross_bus_temps(
            result['xye_temps'], result['rt_temps'], label)

        print_fahrenheit_analysis(
            result['uart_body15_values'], result['uart_a0_frames'], label)

        # Aggregate
        for off in c0c3_scan_offsets:
            agg_c0c3[off] += result['c0c3_bytes'].get(off, Counter())
        for off in c4c6_scan_offsets:
            agg_c4c6[off] += result['c4c6_bytes'].get(off, Counter())
        for off in d0_scan_offsets:
            agg_d0[off] += result['d0_bytes'].get(off, Counter())
        agg_body15 += result['uart_body15_values']
        total_a0 += result['counts'].get('uart_a0', 0)
        all_a0_frames.extend(result['uart_a0_frames'])

        print()

    # ── Aggregate summary ───────────────────────────────────────────────
    print(f"\n{'#' * 72}")
    print(f"  AGGREGATE SUMMARY (all sessions)")
    print(f"{'#' * 72}")

    total_c0c3 = sum(agg_c0c3[c0c3_scan_offsets[0]].values()) if c0c3_scan_offsets and c0c3_scan_offsets[0] in agg_c0c3 else 0
    total_c4c6 = sum(agg_c4c6[c4c6_scan_offsets[0]].values()) if c4c6_scan_offsets and c4c6_scan_offsets[0] in agg_c4c6 else 0
    total_d0   = sum(agg_d0[d0_scan_offsets[0]].values()) if d0_scan_offsets and d0_scan_offsets[0] in agg_d0 else 0

    print_byte_distribution(
        "C0/C3 Response — ALL SESSIONS",
        agg_c0c3, c0c3_scan_offsets, total_c0c3)

    print_byte_distribution(
        "C4/C6 Response — ALL SESSIONS",
        agg_c4c6, c4c6_scan_offsets, total_c4c6)

    print_byte_distribution(
        "D0 Broadcast — ALL SESSIONS",
        agg_d0, d0_scan_offsets, total_d0)

    # ── Key findings ────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"  KEY FINDINGS")
    print(f"{'=' * 72}")

    # Timer bytes
    timer_start_nonzero = sum(cnt for val, cnt in agg_c0c3.get(17, Counter()).items() if val != 0)
    timer_stop_nonzero  = sum(cnt for val, cnt in agg_c0c3.get(18, Counter()).items() if val != 0)
    timer_total = sum(agg_c0c3.get(17, Counter()).values())
    print(f"\n  Timer bytes: byte[17] non-zero: {timer_start_nonzero}/{timer_total}, "
          f"byte[18] non-zero: {timer_stop_nonzero}/{timer_total}")
    if timer_start_nonzero == 0 and timer_stop_nonzero == 0:
        print(f"  -> Timer encoding NOT exercised in any capture. Cannot validate 15-min hypothesis.")
    else:
        print(f"  -> Timer activity detected! Cross-validate with UART timer fields.")

    # L1/L2/L3
    for offset, name in [(27, 'L1'), (28, 'L2'), (29, 'L3')]:
        nonzero = sum(cnt for val, cnt in agg_c0c3.get(offset, Counter()).items() if val != 0)
        total = sum(agg_c0c3.get(offset, Counter()).values())
        print(f"\n  {name} (byte[{offset}]): non-zero: {nonzero}/{total}")
        if nonzero == 0:
            print(f"  -> Constant 0x00 on tested hardware. Matches codeberg README.")
        else:
            print(f"  -> NON-ZERO VALUES FOUND — investigate!")

    # Current draw
    curr_nonzero = sum(cnt for val, cnt in agg_c0c3.get(15, Counter()).items() if val != 0)
    curr_total = sum(agg_c0c3.get(15, Counter()).values())
    print(f"\n  Current draw (byte[15]): non-zero: {curr_nonzero}/{curr_total}")
    if curr_nonzero == 0:
        print(f"  -> Confirmed: always 0x00 on this hardware (Midea XtremeSaveBlue)")
    else:
        print(f"  -> Current data found! Document in protocol_xye.md 2.2")

    # Frequency byte
    freq_ctr = agg_c0c3.get(16, Counter())
    print(f"\n  Frequency (byte[16]): {dict(freq_ctr)}")
    if len(freq_ctr) == 1:
        val = list(freq_ctr.keys())[0]
        print(f"  -> Constant 0x{val:02X} across all sessions")

    # C4/C6 device type and unknown
    devtype_ctr = agg_c4c6.get(19, Counter())
    unk_ctr     = agg_c4c6.get(20, Counter())
    print(f"\n  C4/C6 byte[19] DEVICE_TYPE: {dict(devtype_ctr)}")
    print(f"  C4/C6 byte[20] UNKNOWN:     {dict(unk_ctr)}")
    if len(devtype_ctr) == 1 and list(devtype_ctr.keys())[0] == 0xBC:
        print(f"  -> Confirmed: DEVICE_TYPE = 0xBC (outdoor unit) across all sessions")
    if len(unk_ctr) == 1 and list(unk_ctr.keys())[0] == 0xD6:
        print(f"  -> Confirmed: byte[20] = 0xD6 constant (identity unknown — not a sensor)")

    # Fahrenheit analysis
    print(f"\n  Fahrenheit flag analysis:")
    if agg_body15:
        print(f"  UART C0 body[15] aggregate: {dict(agg_body15)}")
        has_nonzero_nibbles = any(v != 0 for v in agg_body15.keys())
        if has_nonzero_nibbles:
            print(f"  -> Non-zero decimal nibbles present: Celsius mode with decimal precision confirmed")
            print(f"     (mill1000 parse_temperature fahrenheits=False path is active)")
        else:
            print(f"  -> All zeros: no decimal precision data. Cannot determine C/F mode from body[15] alone.")
    else:
        print(f"  UART C0 body[15]: no data available")

    print(f"\n  UART 0xA0 alternative temp frames: {total_a0} total across all sessions")
    if total_a0 > 0:
        print(f"  -> Alternative temperature encoding (OQ-18) IS present — decode and compare")
    else:
        print(f"  -> Not found. OQ-18 encoding not exercised on this hardware.")

    # D0 unexplored region summary
    print(f"\n  D0 broadcast unexplored region (bytes 12-29):")
    for offset in range(12, 30):
        ctr = agg_d0.get(offset, Counter())
        nonzero = sum(cnt for val, cnt in ctr.items() if val != 0)
        total = sum(ctr.values())
        if nonzero > 0:
            top_nonzero = sorted([(v, c) for v, c in ctr.items() if v != 0], key=lambda x: -x[1])[:3]
            nz_str = ', '.join(f'0x{v:02X}:{c}' for v, c in top_nonzero)
            print(f"    byte[{offset}]: {nonzero}/{total} non-zero ({nz_str})")
        else:
            if total > 0:
                print(f"    byte[{offset}]: all zeros ({total} frames)")

    # ── Temperature offset origin analysis ──────────────────────────────
    print_offset_origin_analysis()

    print()


if __name__ == '__main__':
    main()
