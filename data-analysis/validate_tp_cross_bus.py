#!/usr/bin/env python3
"""
validate_tp_cross_bus.py — Cross-compare Tp (discharge temperature) between:
  - XYE/HAHB bus:  C4/C6 response byte[22]  →  (raw - 40) / 2  °C
  - UART R/T bus:  C1 Group-1 (page 0x41) body[14]  →  direct integer °C

Note: XYE byte[19] = 0xBC is a fixed outdoor-unit device-type field, NOT Tp.
      Tp is at byte[22] (confirmed by cross-session comparison with UART).
      UART body[14] = Tp already converted to °C by the outdoor MCU (not a
      raw NTC ADC index — ucPQTempTab is applied internally before transmission).

Only rows where the compressor is running (C1 group-1 compressor-freq > 0) are
included.  Each XYE reading is matched to the nearest UART reading whose
timestamp is within MAX_DELTA_S seconds.

Usage:
    python validate_tp_cross_bus.py <session_dir> [<session_dir> ...]
    python validate_tp_cross_bus.py ../Midea-XtremeSaveBlue-display/Session\ {3..8}
"""

import struct
import sys
import os
from pathlib import Path

# ── ucPQTempTab (256 entries from weex.js) ───────────────────────────────────
UC_PQ_TEMP_TAB = [
    48, 48, 33, 25, 20, 16, 13, 10,  7,  4,   # 0–9
     2,  0,  2,  3,  5,  6,  8,  9, 11, 12,   # 10–19
    13, 14, 15, 16, 17, 18, 19, 20, 21, 22,   # 20–29
    23, 24, 24, 25, 26, 27, 27, 28, 29, 30,   # 30–39
    30, 31, 32, 32, 33, 34, 34, 35, 36, 36,   # 40–49
    37, 37, 38, 39, 39, 40, 40, 41, 41, 42,   # 50–59
    42, 43, 44, 44, 45, 45, 46, 46, 47, 47,   # 60–69
    48, 48, 49, 49, 50, 50, 51, 51, 52, 52,   # 70–79
    53, 53, 54, 54, 55, 55, 56, 56, 56, 57,   # 80–89
    57, 58, 58, 59, 59, 60, 60, 61, 61, 62,   # 90–99
    62, 63, 63, 63, 64, 64, 65, 65, 66, 66,   # 100–109
    67, 67, 68, 68, 69, 69, 69, 70, 70, 71,   # 110–119
    71, 72, 72, 73, 73, 74, 74, 75, 75, 76,   # 120–129
    76, 76, 77, 77, 78, 78, 79, 79, 80, 80,   # 130–139
    81, 81, 82, 82, 83, 83, 84, 84, 85, 85,   # 140–149
    86, 86, 87, 87, 88, 88, 89, 90, 90, 91,   # 150–159
    91, 92, 92, 93, 93, 94, 95, 95, 96, 96,   # 160–169
    97, 98, 98, 99, 99,100,101,101,102,103,   # 170–179
   103,104,105,105,106,107,107,108,109,109,   # 180–189
   110,111,112,112,113,114,115,116,116,117,   # 190–199
   118,119,120,121,122,123,124,125,126,127,   # 200–209
   128,129,130,135,136,137,138,140,141,142,   # 210–219  ← note big jumps
   144,145,147,148,150,152,153,155,157,159,   # 220–229
   161,163,165,168,170,173,175,178,181,185,   # 230–239
   188,192,196,201,206,211,218,225,233,243,   # 240–249
   254,255,255,255,255,255,                   # 250–255
]
assert len(UC_PQ_TEMP_TAB) == 256, f"Table length {len(UC_PQ_TEMP_TAB)}"

MAX_DELTA_S = 2.0   # maximum timestamp gap for a valid pair

# HVAC_shark bus type codes
BUS_XYE       = 0x00
BUS_UART      = 0x01
BUS_DISP_MB1  = 0x02
BUS_RT1       = 0x03

HVAC_MAGIC = b"HVAC_shark"


# ── libpcap reader (no external dependencies) ────────────────────────────────

def _iter_pcap(path: str):
    """Yield (timestamp_s, raw_bytes) for every packet in a libpcap file."""
    with open(path, "rb") as f:
        hdr = f.read(24)
        if len(hdr) < 24:
            return
        magic, ver_maj, ver_min, thiszone, sigfigs, snaplen, network = \
            struct.unpack("<IHHiIII", hdr)
        if magic not in (0xA1B2C3D4, 0xD4C3B2A1):
            raise ValueError(f"Not a libpcap file: {path!r}")
        swap = (magic == 0xD4C3B2A1)

        def u32(b):
            return struct.unpack(("<I" if not swap else ">I"), b)[0]

        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            ts_sec  = u32(rec[0:4])
            ts_usec = u32(rec[4:8])
            incl_len = u32(rec[8:12])
            # orig_len = u32(rec[12:16])  # not needed
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            ts = ts_sec + ts_usec / 1_000_000
            yield ts, data


def _parse_hvac_shark(udp_payload: bytes):
    """Return (bus_type, protocol_bytes) or None if payload is not HVAC_shark."""
    if len(udp_payload) < 13:
        return None
    if not udp_payload.startswith(HVAC_MAGIC):
        return None
    # byte 10 = manufacturer, byte 11 = bus_type, byte 12 = version
    bus_type = udp_payload[11]
    version  = udp_payload[12]
    if version == 0x01:  # extended header
        pos = 13
        for _ in range(3):   # channel_name, circuit_board, comment
            if pos >= len(udp_payload):
                return None
            field_len = udp_payload[pos]
            pos += 1 + field_len
        proto = udp_payload[pos:]
    else:                # legacy: no variable fields
        proto = udp_payload[13:]
    return bus_type, proto


def _udp_payload(eth_frame: bytes):
    """Extract UDP payload from an Ethernet/IPv4/UDP frame."""
    if len(eth_frame) < 14 + 20 + 8:
        return None
    # Ethernet: 14 bytes
    iph = eth_frame[14:]
    ip_ihl = (iph[0] & 0x0F) * 4
    if iph[9] != 17:   # not UDP
        return None
    udph = iph[ip_ihl:]
    if len(udph) < 8:
        return None
    udp_len = struct.unpack("!H", udph[2:4])[0]
    return udph[8: 8 + udp_len - 8]  # strip UDP header


# ── Packet-level decoders ─────────────────────────────────────────────────────

def _decode_xye_c4c6(proto: bytes):
    """Return Tp_raw from XYE C4/C6 response or None.

    Tp is at byte[22], formula (raw - 40) / 2 °C.
    Confirmed via cross-session comparison with UART R/T Tp (direct °C):
      Sessions 3/5/6 show perfect agreement; Sessions 7/8 show overlapping ranges.
    NOTE: byte[19] = 0xBC is a fixed outdoor-unit device-type field, NOT Tp.
    """
    if len(proto) < 23:
        return None
    if proto[0] != 0xAA:
        return None
    if proto[1] not in (0xC4, 0xC6):
        return None
    return proto[22]


def _decode_uart_c1_group1(proto: bytes):
    """Return (compressor_freq_hz, Tp_raw) from R/T C1 Group-1 response or None.

    R/T frame layout (bus_type 0x02 or 0x03):
      byte[0]   = 0x55 (response) or 0xAA (request)
      byte[1]   = device type (0xBC typical)
      byte[2]   = payload length  (total = length + 4)
      byte[3]   = appliance (0xAC)
      byte[4-8] = reserved (5 bytes)
      byte[9]   = protocol version
      byte[10]  = message type
      byte[11]  = body[0] = cmd_id       ← 0xC1
      byte[12]  = body[1]                   0x21
      byte[13]  = body[2]                   0x01
      byte[14]  = body[3] = page            0x41 (group 1)
      byte[15]  = body[4] = compressor actual frequency (Hz, raw)
      byte[16]  = body[5]
      ...
      byte[25]  = body[14] = Tp raw  (ucPQTempTab index)
    """
    if len(proto) < 26:
        return None
    if proto[11] != 0xC1:
        return None
    if proto[14] != 0x41:   # page 0x41 = group 1
        return None
    comp_freq = proto[15]
    tp_raw    = proto[25]
    return comp_freq, tp_raw


# ── Per-session processing ────────────────────────────────────────────────────

def process_session(pcap_path: str, session_label: str):
    """
    Extract (timestamp, bus_type, value) events from a PCAP file.

    Returns two lists:
      xye_events:  [(ts, tp_xye_degC), ...]
      uart_events: [(ts, comp_freq, tp_uart_degC), ...]
    """
    xye_events  = []
    uart_events = []

    for ts, eth_frame in _iter_pcap(pcap_path):
        udp = _udp_payload(eth_frame)
        if udp is None:
            continue
        parsed = _parse_hvac_shark(udp)
        if parsed is None:
            continue
        bus_type, proto = parsed

        if bus_type == BUS_XYE:
            result = _decode_xye_c4c6(proto)
            if result is not None:
                tp_raw  = result
                tp_degc = (tp_raw - 40) / 2.0
                xye_events.append((ts, tp_raw, tp_degc))

        elif bus_type in (BUS_RT1, BUS_DISP_MB1):
            result = _decode_uart_c1_group1(proto)
            if result is not None:
                comp_freq, tp_raw = result
                # body[14] on the R/T bus is already in direct °C.
                # The outdoor unit MCU does the ucPQTempTab conversion internally
                # and sends the result as an integer.
                # Confirmed: Session 6 proto[25]=0x4A=74 → service menu Tp=74°C.
                tp_degc = tp_raw
                uart_events.append((ts, comp_freq, tp_raw, tp_degc))

    return xye_events, uart_events


# ── Comparison ────────────────────────────────────────────────────────────────

def compare(xye_events, uart_events, session_label):
    """
    For each XYE C4/C6 reading, find the nearest UART C1-G1 reading within
    MAX_DELTA_S seconds where the compressor is running (freq > 0).

    Prints a table row per matched pair, plus summary stats.
    """
    # Filter UART events to compressor-running only
    uart_running = [(ts, freq, raw, tc) for (ts, freq, raw, tc) in uart_events
                    if freq > 0]
    if not uart_running:
        print(f"  {session_label}: no UART C1-G1 frames with compressor running")
        return []

    if not xye_events:
        print(f"  {session_label}: no XYE C4/C6 frames found")
        return []

    pairs = []
    for (xts, xraw, xtc) in xye_events:
        # Find nearest UART event in time
        best = min(uart_running, key=lambda u: abs(u[0] - xts))
        delta = abs(best[0] - xts)
        if delta > MAX_DELTA_S:
            continue
        uts, ufreq, uraw, utc = best
        diff = xtc - utc
        pairs.append({
            "session":   session_label,
            "xye_ts":    xts,
            "uart_ts":   uts,
            "delta_s":   best[0] - xts,   # signed
            "xye_raw":   xraw,
            "uart_raw":  uraw,
            "xye_tc":    xtc,
            "uart_tc":   utc,
            "diff_tc":   diff,
            "comp_freq": ufreq,
        })
    return pairs


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(all_pairs):
    if not all_pairs:
        print("No matched pairs found across all sessions.")
        return

    # Header
    print(
        f"\n{'Session':<10} {'t_XYE':>9} {'t_UART':>9} {'dt_s':>6}  "
        f"{'xRaw':>5} {'uRaw':>5}  {'Tp_XYE':>7} {'Tp_UART':>8} {'Diff':>6}  "
        f"{'Hz':>5}",
        flush=True
    )
    print("-" * 80)

    per_session = {}
    for p in all_pairs:
        sess = p["session"]
        per_session.setdefault(sess, []).append(p)
        print(
            f"{sess:<10} {p['xye_ts']:>9.3f} {p['uart_ts']:>9.3f} "
            f"{p['delta_s']:>+6.3f}  "
            f"{p['xye_raw']:>5} {p['uart_raw']:>5}  "
            f"{p['xye_tc']:>7.1f} {p['uart_tc']:>8}  "
            f"{p['diff_tc']:>+6.1f}  "
            f"{p['comp_freq']:>5}"
        )

    # Per-session summary
    print()
    print(f"{'Session':<10} {'Pairs':>6}  {'Mean diff':>10}  {'Max |diff|':>11}  {'Min |diff|':>11}")
    print("-" * 55)
    for sess, ps in sorted(per_session.items()):
        diffs = [p["diff_tc"] for p in ps]
        mean  = sum(diffs) / len(diffs)
        maxd  = max(abs(d) for d in diffs)
        mind  = min(abs(d) for d in diffs)
        print(f"{sess:<10} {len(ps):>6}  {mean:>+10.2f}  {maxd:>11.2f}  {mind:>11.2f}")

    # Overall
    all_diffs = [p["diff_tc"] for p in all_pairs]
    mean  = sum(all_diffs) / len(all_diffs)
    maxd  = max(abs(d) for d in all_diffs)
    mind  = min(abs(d) for d in all_diffs)
    print("-" * 55)
    print(f"{'TOTAL':<10} {len(all_pairs):>6}  {mean:>+10.2f}  {maxd:>11.2f}  {mind:>11.2f}")

    # Value distribution
    print()
    print("Diff distribution (XYE degC - UART degC):")
    from collections import Counter
    cnt = Counter(round(p["diff_tc"]) for p in all_pairs)
    for diff_val, count in sorted(cnt.items()):
        bar = "█" * min(count, 60)
        print(f"  {diff_val:>+4}: {bar} ({count})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dirs = sys.argv[1:]
    if not dirs:
        # Default: look for sessions 3-8 relative to this script
        script_dir = Path(__file__).parent
        base = script_dir.parent / "Midea-XtremeSaveBlue-display"
        dirs = sorted(str(base / f"Session {i}") for i in range(3, 9))
        dirs = [d for d in dirs if Path(d).exists()]

    if not dirs:
        print("Usage: tp_compare.py <session_dir> [...]")
        sys.exit(1)

    all_pairs = []
    for d in dirs:
        pcap = Path(d) / "session.pcap"
        if not pcap.exists():
            print(f"[skip] {d}: no session.pcap")
            continue
        label = Path(d).name
        print(f"[read] {label} — {pcap}")
        xye_events, uart_events = process_session(str(pcap), label)
        print(f"       XYE C4/C6 frames : {len(xye_events):>5}")
        print(f"       UART C1-G1 frames: {len(uart_events):>5}  "
              f"(compressor running: {sum(1 for e in uart_events if e[1] > 0)})")
        pairs = compare(xye_events, uart_events, label)
        print(f"       Matched pairs    : {len(pairs):>5}")
        all_pairs.extend(pairs)

    report(all_pairs)


if __name__ == "__main__":
    main()
