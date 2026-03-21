#!/usr/bin/env python3
"""
Midea HVAC Bus Logic-Dump Converter
Converts a Saleae-style CSV serial dump into reassembled packets.

Supports two output modes:
  - CSV  (default)  → channel, start_time, packet_len, packet_content, …
  - pcap (--pcap)   → Wireshark-ready capture with HVAC_shark v2 framing

When a channels.yaml is found (or given via --config), channel metadata
(circuitBoard, comment) is embedded in the HVAC_shark v2 header so the
Wireshark dissector can display it.

Input CSV columns:  name, type, start_time, duration, data
Output CSV columns: channel, start_time, packet_len, packet_content, start_byte

HVAC_shark v2 header layout:
  Offset  Size  Field
  0       10    Magic "HVAC_shark"
  10      1     Manufacturer (0x01 = Midea)
  11      1     Bus type     (0x00=XYE, 0x01=UART, 0x02=disp-mainboard_1, 0x03=r-t_1, 0x04=ir_raw)
  12      1     Version      (0x00 = legacy, 0x01 = extended)
  --- extended fields (version 0x01) ---
  13      1     logicChannel name length (N)
  14      N     logicChannel name        (UTF-8)
  14+N    1     circuitBoard length      (M)
  15+N    M     circuitBoard             (UTF-8)
  15+N+M  1     comment length           (C)
  16+N+M  C     comment                  (UTF-8)
  --- XYE protocol data follows ---
"""

import csv as csvmod
import struct
import sys
import os
import statistics
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
GAP_MULTIPLIER     = 5
VALID_START_BYTES  = {0xAA, 0x55}

HVAC_SHARK_MAGIC   = b"HVAC_shark"
MANUFACTURER_MIDEA = 0x01
HEADER_VERSION_V1  = 0x01

BUS_TYPE_MAP = {
    "xye":              0x00,
    "uart":             0x01,
    "disp-mainboard_1": 0x02,
    "r-t_1":            0x03,
    "ir_raw":           0x04,
}

PCAP_MAGIC         = 0xA1B2C3D4
LINKTYPE_ETHERNET  = 1
# ──────────────────────────────────────────────────────────────────────────────


# ── Simple YAML loader (stdlib-only, handles our channels.yaml) ──────────────

def _load_yaml(path: str) -> dict:
    """Minimal YAML parser for channels.yaml — no PyYAML dependency."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        pass

    # Fallback: parse the flat structure we actually use
    config: dict = {"channels": []}
    current_channel: dict | None = None

    with open(path) as f:
        for raw_line in f:
            line = raw_line.split("#")[0].rstrip()       # strip comments
            if not line or line.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip())
            stripped = line.strip()

            # top-level key: value
            if indent == 0 and ":" in stripped and not stripped.startswith("-"):
                key, _, val = stripped.partition(":")
                val = val.strip().strip('"').strip("'")
                if key.strip() != "channels":
                    config[key.strip()] = val

            # list item start (- name: ...)
            elif stripped.startswith("- "):
                if current_channel is not None:
                    config["channels"].append(current_channel)
                current_channel = {}
                pair = stripped[2:].strip()
                if ":" in pair:
                    k, _, v = pair.partition(":")
                    current_channel[k.strip()] = v.strip().strip('"').strip("'")

            # continuation key inside a list item
            elif indent >= 4 and ":" in stripped and current_channel is not None:
                k, _, v = stripped.partition(":")
                current_channel[k.strip()] = v.strip().strip('"').strip("'")

    if current_channel is not None:
        config["channels"].append(current_channel)

    return config


# ── CSV loading & packet extraction (stdlib csv) ─────────────────────────────

def load_dump(path: str) -> list[dict]:
    """Load Saleae CSV export, return sorted data-byte records."""
    records: list[dict] = []
    with open(path, newline="") as f:
        reader = csvmod.DictReader(f, quotechar='"')
        for row in reader:
            if row["type"] == "data":
                records.append({
                    "name":       row["name"],
                    "start_time": float(row["start_time"]),
                    "duration":   float(row["duration"]),
                    "byte_val":   int(row["data"], 16),
                })
    records.sort(key=lambda r: r["start_time"])
    return records


def extract_packets(records: list[dict],
                    gap_multiplier: float = GAP_MULTIPLIER) -> list[dict]:
    """Group bytes into packets per channel using gap detection."""
    from collections import defaultdict
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_channel[rec["name"]].append(rec)

    packets: list[dict] = []
    for channel, recs in by_channel.items():
        recs.sort(key=lambda r: r["start_time"])
        durations = [r["duration"] for r in recs]
        median_dur = statistics.median(durations)
        gap_threshold = median_dur * gap_multiplier

        pkt_start = 0
        for i in range(1, len(recs)):
            prev_end = recs[i - 1]["start_time"] + recs[i - 1]["duration"]
            gap = recs[i]["start_time"] - prev_end
            if gap > gap_threshold:
                _flush(packets, recs, channel, pkt_start, i - 1)
                pkt_start = i

        _flush(packets, recs, channel, pkt_start, len(recs) - 1)

    packets.sort(key=lambda p: p["start_time"])
    return packets


def _flush(packets: list, recs: list[dict], channel: str,
           start: int, end: int):
    pkt_bytes = [recs[i]["byte_val"] for i in range(start, end + 1)]
    if not pkt_bytes:
        return
    start_byte = pkt_bytes[0]
    packets.append({
        "channel":         channel,
        "start_time":      recs[start]["start_time"],
        "packet_len":      len(pkt_bytes),
        "raw_bytes":       pkt_bytes,
        "packet_content":  " ".join(f"{b:02X}" for b in pkt_bytes),
        "start_byte":      f"0x{start_byte:02X}",
        "valid_start":     start_byte in VALID_START_BYTES,
    })


# ── IR raw pulse-width decoder ───────────────────────────────────────────────

# Timing thresholds (seconds) for Midea-style NEC IR encoding
IR_HEADER_MARK_MIN  = 0.003    # header mark  >3 ms
IR_HEADER_SPACE_MIN = 0.003    # header space >3 ms
IR_BIT_SPACE_THRESH = 0.001    # space >1 ms → bit 1, else bit 0
IR_BITS_PER_FRAME   = 48       # 6 bytes per frame


def load_ir_raw(path: str, channel_name: str) -> list[tuple[float, int]]:
    """Load a raw timing CSV (Time [s], <channel>) into (timestamp, level) tuples."""
    transitions: list[tuple[float, int]] = []
    with open(path, newline="") as f:
        reader = csvmod.DictReader(f)
        for row in reader:
            transitions.append((float(row["Time [s]"]), int(row[channel_name])))
    return transitions


def decode_ir_frames(transitions: list[tuple[float, int]],
                     channel_name: str) -> list[dict]:
    """Decode NEC-like IR frames from raw signal transitions.

    Active-low convention (TSOP receiver): 0 = mark (IR burst), 1 = space (idle).
    Each frame: ~4.4 ms header mark + ~4.4 ms header space + 48 data bits + stop mark.
    """
    packets: list[dict] = []
    i = 0
    n = len(transitions)

    while i < n - 4:
        # Look for header: transition to 0 (mark start)
        if transitions[i][1] != 0:
            i += 1
            continue

        # Header mark duration
        if transitions[i + 1][1] != 1:
            i += 1
            continue
        mark_dur = transitions[i + 1][0] - transitions[i][0]
        if mark_dur < IR_HEADER_MARK_MIN:
            i += 1
            continue

        # Header space duration
        if transitions[i + 2][1] != 0:
            i += 2
            continue
        space_dur = transitions[i + 2][0] - transitions[i + 1][0]
        if space_dur < IR_HEADER_SPACE_MIN:
            i += 2
            continue

        # Decode data bits
        frame_start_time = transitions[i][0]
        bits: list[int] = []
        j = i + 2  # points to first data-bit mark start (level 0)

        while j + 2 < n and len(bits) < IR_BITS_PER_FRAME:
            if transitions[j][1] != 0:
                break
            # mark end → space start
            space_start = transitions[j + 1][0]
            # space end → next mark start (or end of frame)
            next_mark = transitions[j + 2][0]
            bit_space = next_mark - space_start
            if bit_space > 0.005:  # too long → not a data bit
                break
            bits.append(1 if bit_space > IR_BIT_SPACE_THRESH else 0)
            j += 2

        if len(bits) == IR_BITS_PER_FRAME:
            # Assemble bytes (MSB first)
            raw_bytes: list[int] = []
            for b in range(0, IR_BITS_PER_FRAME, 8):
                val = 0
                for k in range(8):
                    val = (val << 1) | bits[b + k]
                raw_bytes.append(val)

            complement_ok = all(
                raw_bytes[p] ^ raw_bytes[p + 1] == 0xFF
                for p in range(0, 6, 2)
            )

            packets.append({
                "channel":         channel_name,
                "start_time":      frame_start_time,
                "packet_len":      len(raw_bytes),
                "raw_bytes":       raw_bytes,
                "packet_content":  " ".join(f"{b:02X}" for b in raw_bytes),
                "start_byte":      f"0x{raw_bytes[0]:02X}",
                "valid_start":     complement_ok,
            })

        i = j  # advance past decoded (or failed) frame
        continue

    return packets


def load_and_decode_ir_channels(config: dict,
                                session_dir: Path) -> list[dict]:
    """Find ir_raw channels in config, load their raw CSV, decode IR frames."""
    raw_csv_name = config.get("RawCSV")
    if not raw_csv_name:
        return []

    raw_csv_path = session_dir / raw_csv_name
    if not raw_csv_path.exists():
        print(f"[!] Raw CSV not found: {raw_csv_path}")
        return []

    ir_channels = [
        ch for ch in config.get("channels", [])
        if ch.get("busType") == "ir_raw" and ch.get("file") == "raw"
    ]
    if not ir_channels:
        return []

    all_packets: list[dict] = []
    for ch in ir_channels:
        name = ch.get("name", "")
        if not name:
            continue
        print(f"[*] Decoding IR channel: {name} from {raw_csv_path.name}")
        transitions = load_ir_raw(str(raw_csv_path), name)
        print(f"    {len(transitions):,} transitions")
        packets = decode_ir_frames(transitions, name)
        complement_ok = sum(1 for p in packets if p["valid_start"])
        print(f"    {len(packets)} IR frames decoded "
              f"({complement_ok} complement-OK)")
        all_packets.extend(packets)

    return all_packets


# ── HVAC_shark v2 header builder ─────────────────────────────────────────────

def build_hvac_shark_payload(raw_bytes: list[int],
                             channel_name: str = "",
                             circuit_board: str = "",
                             comment: str = "",
                             bus_type: str = "xye") -> bytes:
    """Build HVAC_shark payload: v2 header + protocol data."""
    bus_code = BUS_TYPE_MAP.get(bus_type, 0xFF)
    buf = bytearray()
    buf += HVAC_SHARK_MAGIC                                  # 10 B
    buf += struct.pack("B", MANUFACTURER_MIDEA)              #  1 B
    buf += struct.pack("B", bus_code)                        #  1 B
    buf += struct.pack("B", HEADER_VERSION_V1)               #  1 B  (version=1)

    for field in (channel_name, circuit_board, comment):
        encoded = field.encode("utf-8")
        buf += struct.pack("B", len(encoded))
        buf += encoded

    buf += bytes(raw_bytes)
    return bytes(buf)


# ── pcap writer (stdlib struct, no scapy) ─────────────────────────────────────

def _ip_checksum(header: bytes) -> int:
    """RFC 1071 Internet checksum."""
    if len(header) % 2:
        header += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(header) // 2), header))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return (~s) & 0xFFFF


def _build_frame(payload: bytes, src_port: int, dst_port: int = 22222) -> bytes:
    """Wrap payload in Ethernet / IPv4 / UDP."""
    # UDP
    udp_len = 8 + len(payload)
    udp_hdr = struct.pack("!HHHH", src_port, dst_port, udp_len, 0)

    # IPv4 (checksum computed after)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack("!BBHHHBBH4s4s",
        0x45, 0, ip_total,
        0, 0x4000,
        64, 17, 0,                       # TTL=64, proto=UDP, cksum=0
        b"\x7f\x00\x00\x01",             # src = 127.0.0.1
        b"\x7f\x00\x00\x01",             # dst = 127.0.0.1
    )
    cksum = _ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack("!H", cksum) + ip_hdr[12:]

    # Ethernet
    eth_hdr = struct.pack("!6s6sH",
        b"\x00" * 6, b"\x00" * 6, 0x0800)

    return eth_hdr + ip_hdr + udp_hdr + payload


def write_pcap(filepath: str, packets: list[dict],
               channel_meta: dict[str, dict]):
    """Write a libpcap file from reassembled packets."""
    channel_names = list(channel_meta.keys()) if channel_meta else []

    with open(filepath, "wb") as f:
        # Global header
        f.write(struct.pack("<IHHiIII",
            PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_ETHERNET))

        for pkt in packets:
            ch = pkt["channel"]
            meta = channel_meta.get(ch, {})
            board    = meta.get("circuitBoard", "")
            comment  = meta.get("comment", "")
            bus_type = meta.get("busType", "xye")

            hvac_payload = build_hvac_shark_payload(
                pkt["raw_bytes"], ch, board, comment, bus_type)

            src_port = (channel_names.index(ch) + 1) if ch in channel_names else 0
            frame = _build_frame(hvac_payload, src_port)

            ts = pkt["start_time"]
            ts_sec  = int(ts)
            ts_usec = int((ts - ts_sec) * 1_000_000)

            f.write(struct.pack("<IIII", ts_sec, ts_usec,
                                len(frame), len(frame)))
            f.write(frame)


# ── CSV writer ────────────────────────────────────────────────────────────────

def write_csv(filepath: str, packets: list[dict]):
    """Write the legacy midea_packets.csv output."""
    fieldnames = ["channel", "start_time", "packet_len",
                  "packet_content", "start_byte", "valid_start"]
    with open(filepath, "w", newline="") as f:
        writer = csvmod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pkt in packets:
            writer.writerow({k: pkt[k] for k in fieldnames})


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_summary(packets: list[dict]):
    valid = sum(1 for p in packets if p["valid_start"])
    invalid = len(packets) - valid
    print(f"    {len(packets):,} packets  |  "
          f"{valid:,} valid (0xAA/0x55)  |  {invalid} other")

    print("\n    Packets per channel:")
    from collections import Counter
    for ch, cnt in Counter(p["channel"] for p in packets).most_common():
        print(f"      {ch}: {cnt}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Convert Saleae CSV serial dumps to packet CSV or pcap")
    parser.add_argument("session_dir", nargs="?", default=".",
        help="Session directory containing channels.yaml and the CSV export")
    parser.add_argument("-c", "--config",
        help="Path to channels.yaml (default: <session_dir>/channels.yaml)")
    parser.add_argument("-i", "--input",
        help="Input CSV (overrides channels.yaml 'csv' field)")
    parser.add_argument("-o", "--output",
        help="Output file (.csv or .pcap; default: midea_packets.csv)")
    parser.add_argument("--pcap", action="store_true",
        help="Write pcap output (default output becomes session.pcap)")
    parser.add_argument("--gap-multiplier", type=float, default=GAP_MULTIPLIER,
        help=f"Gap threshold multiplier (default: {GAP_MULTIPLIER})")
    args = parser.parse_args()

    session_dir = Path(args.session_dir)

    # ── Load channels.yaml ──
    config_path = Path(args.config) if args.config else session_dir / "channels.yaml"
    channel_meta: dict[str, dict] = {}
    csv_from_yaml = None

    if config_path.exists():
        print(f"[*] Config: {config_path}")
        config = _load_yaml(str(config_path))
        csv_from_yaml = config.get("csv")
        for ch in config.get("channels", []):
            name = ch.get("name", "")
            if name:
                channel_meta[name] = ch
        for name, meta in channel_meta.items():
            print(f"    {name}: {meta.get('comment', '')}")
    else:
        print(f"[*] No channels.yaml found at {config_path}, proceeding without metadata")

    # ── Resolve input CSV ──
    if args.input:
        in_path = Path(args.input)
    elif csv_from_yaml:
        in_path = session_dir / csv_from_yaml
    else:
        in_path = session_dir / "logic-dump.csv"

    # ── Resolve output ──
    if args.output:
        out_path = Path(args.output)
    elif args.pcap:
        out_path = session_dir / "session.pcap"
    else:
        out_path = session_dir / "midea_packets.csv"

    is_pcap = args.pcap or str(out_path).endswith(".pcap")

    # ── Process serial channels ──
    print(f"[*] Loading: {in_path}")
    records = load_dump(str(in_path))
    unique_channels = set(r["name"] for r in records)
    print(f"    {len(records):,} bytes across {len(unique_channels)} channels")

    print(f"[*] Extracting packets (gap_multiplier={args.gap_multiplier})...")
    packets = extract_packets(records, args.gap_multiplier)
    _print_summary(packets)

    # ── Process IR raw channels ──
    if config_path.exists():
        ir_packets = load_and_decode_ir_channels(config, session_dir)
        if ir_packets:
            packets.extend(ir_packets)
            packets.sort(key=lambda p: p["start_time"])
            print(f"[*] Merged {len(ir_packets)} IR frames -> "
                  f"{len(packets)} total packets")

    if is_pcap:
        print(f"\n[*] Writing pcap: {out_path}")
        write_pcap(str(out_path), packets, channel_meta)
    else:
        print(f"\n[*] Writing CSV: {out_path}")
        write_csv(str(out_path), packets)

    print(f"[ok] Saved -> {out_path}")


if __name__ == "__main__":
    main()
