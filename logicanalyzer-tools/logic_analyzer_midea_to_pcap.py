#!/usr/bin/env python3
"""
Midea HVAC Bus Logic-Dump Converter
Converts logic-analyzer captures into reassembled packets.

Supports two input modes:
  serial (default)  – Saleae-style CSV with pre-decoded UART bytes
  hahb              – Saleae digital waveform CSV; two-track HAHB decoder

Supports two output modes:
  CSV  (default)    → channel, start_time, packet_len, packet_content, …
  pcap (--pcap)     → Wireshark-ready capture with HVAC_shark v2 framing

When a channels.yaml is found (or given via --config), channel metadata
(connectedComponents, comment) is embedded in the HVAC_shark v2 header so the
Wireshark dissector can display it.

Serial-mode input CSV columns:  name, type, start_time, duration, data
Output CSV columns:             channel, start_time, packet_len, packet_content, start_byte

HAHB-mode input CSV columns:    <time_col>, <master_col> [, <slave_col>]
  HAHB frames are written with bus type XYE.

HVAC_shark v2 header layout:
  Offset  Size  Field
  0       10    Magic "HVAC_shark"
  10      1     Manufacturer (0x01 = Midea)
  11      1     Bus type     (0x00=XYE, 0x01=UART, 0x02=disp-mainboard_1,
                               0x03=r-t_1, 0x04=ir_raw)
  12      1     Version      (0x00 = legacy, 0x01 = extended)
  --- extended fields (version 0x01) ---
  13      1     logicChannel name length (N)
  14      N     logicChannel name        (UTF-8)
  14+N    1     connectedComponents length      (M)
  15+N    M     connectedComponents             (UTF-8)
  15+N+M  1     comment length           (C)
  16+N+M  C     comment                  (UTF-8)
  --- protocol data follows ---
"""

import csv as csvmod
import struct
import sys
from pathlib import Path

from decoder_midea_serial import load_dump, extract_packets, GAP_MULTIPLIER
from decoder_midea_ir     import load_and_decode_ir_channels
try:
    from decoder_midea_hahb import load_and_decode_hahb
except ImportError:
    load_and_decode_hahb = None  # numpy not installed — HAHB decoding unavailable

# ── Constants ─────────────────────────────────────────────────────────────────
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

PCAP_MAGIC        = 0xA1B2C3D4
LINKTYPE_ETHERNET = 1
# ──────────────────────────────────────────────────────────────────────────────


# ── Minimal YAML loader (stdlib-only) ─────────────────────────────────────────

def _load_yaml(path: str) -> dict:
    """Minimal YAML parser for channels.yaml — no PyYAML dependency."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        pass

    config: dict = {"channels": []}
    current_channel: dict | None = None

    with open(path) as f:
        for raw_line in f:
            line = raw_line.split("#")[0].rstrip()
            if not line or line.startswith("#"):
                continue

            indent   = len(line) - len(line.lstrip())
            stripped = line.strip()

            if indent == 0 and ":" in stripped and not stripped.startswith("-"):
                key, _, val = stripped.partition(":")
                val = val.strip().strip('"').strip("'")
                if key.strip() != "channels":
                    config[key.strip()] = val

            elif stripped.startswith("- "):
                if current_channel is not None:
                    config["channels"].append(current_channel)
                current_channel = {}
                pair = stripped[2:].strip()
                if ":" in pair:
                    k, _, v = pair.partition(":")
                    current_channel[k.strip()] = v.strip().strip('"').strip("'")

            elif indent >= 4 and ":" in stripped and current_channel is not None:
                k, _, v = stripped.partition(":")
                current_channel[k.strip()] = v.strip().strip('"').strip("'")

    if current_channel is not None:
        config["channels"].append(current_channel)

    return config


# ── HVAC_shark v2 header ───────────────────────────────────────────────────────

def build_hvac_shark_payload(raw_bytes: list[int],
                             channel_name: str = "",
                             circuit_board: str = "",
                             comment: str = "",
                             bus_type: str = "xye") -> bytes:
    """Build HVAC_shark payload: v2 header + protocol data."""
    bus_code = BUS_TYPE_MAP.get(bus_type, 0xFF)
    buf = bytearray()
    buf += HVAC_SHARK_MAGIC
    buf += struct.pack("B", MANUFACTURER_MIDEA)
    buf += struct.pack("B", bus_code)
    buf += struct.pack("B", HEADER_VERSION_V1)

    for field in (channel_name, circuit_board, comment):
        encoded = field.encode("utf-8")
        buf += struct.pack("B", len(encoded))
        buf += encoded

    buf += bytes(raw_bytes)
    return bytes(buf)


# ── pcap writer ───────────────────────────────────────────────────────────────

def _ip_checksum(header: bytes) -> int:
    if len(header) % 2:
        header += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(header) // 2), header))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return (~s) & 0xFFFF


def _build_frame(payload: bytes, src_port: int, dst_port: int = 22222) -> bytes:
    """Wrap payload in Ethernet / IPv4 / UDP."""
    udp_len = 8 + len(payload)
    udp_hdr = struct.pack("!HHHH", src_port, dst_port, udp_len, 0)

    ip_total = 20 + udp_len
    ip_hdr = struct.pack("!BBHHHBBH4s4s",
        0x45, 0, ip_total, 0, 0x4000,
        64, 17, 0,
        b"\x7f\x00\x00\x01",
        b"\x7f\x00\x00\x01",
    )
    cksum  = _ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack("!H", cksum) + ip_hdr[12:]

    eth_hdr = struct.pack("!6s6sH", b"\x00" * 6, b"\x00" * 6, 0x0800)
    return eth_hdr + ip_hdr + udp_hdr + payload


def write_pcap(filepath: str, packets: list[dict],
               channel_meta: dict[str, dict]):
    """Write a libpcap file from reassembled packets."""
    channel_names = list(channel_meta.keys()) if channel_meta else []

    with open(filepath, "wb") as f:
        f.write(struct.pack("<IHHiIII",
            PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_ETHERNET))

        for pkt in packets:
            ch      = pkt["channel"]
            meta    = channel_meta.get(ch, {})
            board   = meta.get("connectedComponents", "")
            comment = meta.get("comment", "")
            direction = meta.get("direction", "")
            bus_type = meta.get("busType", "xye")
            # R/T bidirectional: override per-frame using start byte
            # 0xAA = bus adapter → display (queries/commands) = toACdisplay
            # 0x55 = display → bus adapter (responses) = fromACdisplay
            if bus_type == "r-t_1" and direction in ("unknown", ""):
                raw = pkt["raw_bytes"]
                if raw and raw[0] == 0xAA:
                    direction = "toACdisplay"
                elif raw and raw[0] == 0x55:
                    direction = "fromACdisplay"
            if direction and f"[{direction}]" not in comment:
                comment = f"{comment} [{direction}]" if comment else f"[{direction}]"

            hvac_payload = build_hvac_shark_payload(
                pkt["raw_bytes"], ch, board, comment, bus_type)

            src_port = (channel_names.index(ch) + 10001) if ch in channel_names else 10000
            frame    = _build_frame(hvac_payload, src_port)

            ts      = pkt["start_time"]
            ts_sec  = int(ts)
            ts_usec = int((ts - ts_sec) * 1_000_000)

            f.write(struct.pack("<IIII", ts_sec, ts_usec,
                                len(frame), len(frame)))
            f.write(frame)


# ── CSV writer ────────────────────────────────────────────────────────────────

def write_csv(filepath: str, packets: list[dict],
              channel_meta: dict[str, dict] | None = None):
    fieldnames = ["channel", "direction", "start_time", "packet_len",
                  "packet_content", "start_byte", "valid_start"]
    channel_meta = channel_meta or {}
    with open(filepath, "w", newline="") as f:
        writer = csvmod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pkt in packets:
            meta = channel_meta.get(pkt.get("channel", ""), {})
            direction = meta.get("direction", "")
            bus_type = meta.get("busType", "")
            # R/T per-frame direction from start byte
            # 0xAA = bus adapter → display, 0x55 = display → bus adapter
            if bus_type == "r-t_1" and direction in ("unknown", ""):
                raw = pkt.get("raw_bytes", [])
                if raw and raw[0] == 0xAA:
                    direction = "toACdisplay"
                elif raw and raw[0] == 0x55:
                    direction = "fromACdisplay"
            row = {k: pkt.get(k, "") for k in fieldnames}
            row["direction"] = direction
            writer.writerow(row)



def write_outputs(out_path: Path, packets: list[dict],
                  channel_meta: dict[str, dict],
                  only_pcap: bool = False, only_csv: bool = False):
    """Write pcap and/or csv from the same decoded packets."""
    pcap_path = out_path.with_suffix(".pcap")
    csv_path  = (out_path.with_suffix(".csv") if out_path.suffix == ".pcap"
                 else out_path.parent / "midea_packets.csv")

    wrote = []
    if not only_csv:
        print(f"[*] Writing pcap: {pcap_path}")
        write_pcap(str(pcap_path), packets, channel_meta)
        wrote.append(str(pcap_path))
    if not only_pcap:
        print(f"[*] Writing CSV:  {csv_path}")
        write_csv(str(csv_path), packets, channel_meta)
        wrote.append(str(csv_path))

    print(f"[ok] Saved -> {' + '.join(wrote)}")


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _print_summary(packets: list[dict]):
    valid   = sum(1 for p in packets if p["valid_start"])
    invalid = len(packets) - valid
    print(f"    {len(packets):,} packets  |  "
          f"{valid:,} valid (0xAA/0x55)  |  {invalid} other")

    from collections import Counter
    print("\n    Packets per channel:")
    for ch, cnt in Counter(p["channel"] for p in packets).most_common():
        print(f"      {ch}: {cnt}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert logic-analyzer captures (Saleae) to packet CSV or pcap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (serial mode — default):
  %(prog)s session/
  %(prog)s session/ --pcap
  %(prog)s -i dump.csv -o out.pcap --pcap

Examples (HAHB mode):
  %(prog)s --hahb digital.csv --hahb-master ch6 --hahb-slave ch7 -o session.pcap
  %(prog)s --hahb digital.csv --hahb-master ch6 -o master.pcap
  %(prog)s --hahb digital.csv --hahb-master ch6 --hahb-slave ch7 --hahb-subtract -o session.pcap
""")

    # Serial-mode args
    parser.add_argument("session_dir", nargs="?", default=".",
        help="Session directory containing channels.yaml and CSV export "
             "(serial mode, ignored in HAHB mode)")
    parser.add_argument("-c", "--config",
        help="Path to channels.yaml (default: <session_dir>/channels.yaml)")
    parser.add_argument("-i", "--input",
        help="Input CSV (overrides channels.yaml 'csv' field)")
    parser.add_argument("--gap-multiplier", type=float, default=GAP_MULTIPLIER,
        help=f"Byte-gap threshold multiplier for serial mode (default: {GAP_MULTIPLIER})")

    # HAHB-mode args
    hahb = parser.add_argument_group("HAHB mode")
    hahb.add_argument("--hahb", metavar="DIGITAL_CSV",
        help="Digital waveform CSV exported by Saleae (activates HAHB decoder)")
    hahb.add_argument("--hahb-time-col", default="time", metavar="COL",
        help="Timestamp column name in the digital CSV (default: time)")
    hahb.add_argument("--hahb-master", metavar="COL",
        help="Column name for the master / combined bus signal")
    hahb.add_argument("--hahb-slave", metavar="COL",
        help="Column name for the slave signal (optional)")
    hahb.add_argument("--hahb-master-label", default="master", metavar="LABEL",
        help="Channel label for master in pcap output (default: master)")
    hahb.add_argument("--hahb-slave-label",  default="slave",  metavar="LABEL",
        help="Channel label for slave in pcap output (default: slave)")
    hahb.add_argument("--hahb-subtract", action="store_true",
        help="Remove master-duplicate frames from slave output")

    # Common output args
    parser.add_argument("-o", "--output",
        help="Output base path (auto-named if omitted)")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--pcap", action="store_true",
        help="Write only pcap (skip csv)")
    fmt.add_argument("--csv", action="store_true",
        help="Write only csv (skip pcap)")

    args = parser.parse_args()

    # ── HAHB mode ──────────────────────────────────────────────────────────────
    if args.hahb:
        if not args.hahb_master and not args.hahb_slave:
            parser.error("--hahb requires at least --hahb-master or --hahb-slave")

        if load_and_decode_hahb is None:
            parser.error("HAHB decoding requires numpy: pip install numpy")

        master_label = args.hahb_master_label
        slave_label  = args.hahb_slave_label

        master_pkts, slave_pkts = load_and_decode_hahb(
            args.hahb,
            time_col     = args.hahb_time_col,
            master_col   = args.hahb_master,
            slave_col    = args.hahb_slave,
            master_label = master_label,
            slave_label  = slave_label,
            subtract     = args.hahb_subtract,
        )

        all_packets = sorted(
            master_pkts + slave_pkts,
            key=lambda p: p["start_time"],
        )

        # Build channel_meta: HAHB frames are XYE on the wire
        channel_meta: dict[str, dict] = {}
        if args.hahb_master:
            channel_meta[master_label] = {
                "busType":      "xye",
                "connectedComponents": "",
                "comment":      "HAHB master",
            }
        if args.hahb_slave:
            channel_meta[slave_label] = {
                "busType":      "xye",
                "connectedComponents": "",
                "comment":      "HAHB slave" + (" (subtracted)" if args.hahb_subtract else ""),
            }

        out_path = Path(args.output) if args.output else Path("session.pcap")

        _print_summary(all_packets)
        write_outputs(out_path, all_packets, channel_meta,
                      only_pcap=args.pcap, only_csv=args.csv)
        return

    # ── Serial mode ────────────────────────────────────────────────────────────
    session_dir = Path(args.session_dir)

    if not session_dir.is_dir():
        parser.error(
            f"Session directory not found: {session_dir}\n\n"
            f"Usage:  {parser.prog} <session_dir> [--pcap]\n\n"
            f"The session directory must contain a channels.yaml and the\n"
            f"exported CSV files from the Saleae logic analyzer.\n"
            f"See --help for full usage and examples."
        )

    config_path  = Path(args.config) if args.config else session_dir / "channels.yaml"
    channel_meta = {}
    config: dict = {}

    # Bus types decoded from Saleae pre-decoded UART byte CSV
    SERIAL_BUS_TYPES = {"xye", "uart", "disp-mainboard_1", "r-t_1"}

    if config_path.exists():
        print(f"[*] Config: {config_path}")
        config = _load_yaml(str(config_path))
        for ch in config.get("channels", []):
            name = ch.get("name", "")
            if name:
                channel_meta[name] = ch
        VALID_DIRECTIONS = {"toACmainboard", "fromACmainboard",
                            "toACdisplay", "fromACdisplay",
                            "toACbusadapter_HAHB", "fromACbusadapter_HAHB",
                            "unknown", ""}
        for name, meta in channel_meta.items():
            d = meta.get("direction", "")
            d_label = f"  [{d}]" if d else ""
            if d and d not in VALID_DIRECTIONS:
                print(f"    WARNING: {name}: invalid direction '{d}' "
                      f"(expected: {', '.join(sorted(VALID_DIRECTIONS - {''}))})")
            print(f"    {name}: {meta.get('comment', '')}{d_label}")
    else:
        print(f"[*] No channels.yaml found at {config_path}, proceeding without metadata")

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = session_dir / "session.pcap"

    # Collect unique CSV files from serial channels (per-channel csv field)
    serial_csvs: list[str] = []
    for ch in config.get("channels", []):
        if ch.get("busType") in SERIAL_BUS_TYPES:
            csv_name = ch.get("csv")
            if csv_name and csv_name not in serial_csvs:
                serial_csvs.append(csv_name)

    if args.input:
        print(f"[*] Loading: {args.input}")
        records = load_dump(args.input)
    elif serial_csvs:
        records = []
        for csv_name in serial_csvs:
            p = session_dir / csv_name
            print(f"[*] Loading: {p}")
            records.extend(load_dump(str(p)))
        records.sort(key=lambda r: r["start_time"])
    else:
        fallback = session_dir / "logic-dump.csv"
        if not fallback.exists():
            print(f"[!] ERROR: No input data found in {session_dir}")
            print(f"    Expected: channels.yaml with CSV references, "
                  f"-i <csv>, or {fallback.name}")
            print(f"    Run '{parser.prog} --help' for usage.")
            sys.exit(1)
        print(f"[*] Loading: {fallback}")
        records = load_dump(str(fallback))

    unique_channels = set(r["name"] for r in records)
    print(f"    {len(records):,} bytes across {len(unique_channels)} channels")

    print(f"[*] Extracting packets (gap_multiplier={args.gap_multiplier})...")
    packets = extract_packets(records, args.gap_multiplier)
    _print_summary(packets)

    if config_path.exists():
        ir_packets = load_and_decode_ir_channels(config, session_dir)
        if ir_packets:
            packets.extend(ir_packets)
            packets.sort(key=lambda p: p["start_time"])
            print(f"[*] Merged {len(ir_packets)} IR frames -> "
                  f"{len(packets)} total packets")

    # ── Auto-detect HAHB channels from channels.yaml ──────────────────────────
    # Channels with busType "hahb_raw_chip" are decoded via the HAHB pipeline
    # and written as XYE frames in the pcap.
    # channelframes "sum"    → master (sees all bus traffic)
    # channelframes "single" → slave  (one direction only)
    hahb_channels = [
        ch for ch in config.get("channels", [])
        if ch.get("busType") == "hahb_raw_chip"
    ]
    if hahb_channels:
        # Group by source CSV (multiple HAHB captures could share one session)
        hahb_by_csv: dict[str, list[dict]] = {}
        for ch in hahb_channels:
            csv_name = ch.get("csv", "")
            hahb_by_csv.setdefault(csv_name, []).append(ch)

        for csv_name, chs in hahb_by_csv.items():
            hahb_path = session_dir / csv_name
            if not hahb_path.exists():
                print(f"[!] HAHB CSV not found: {hahb_path}, skipping")
                continue

            master_ch = next(
                (c for c in chs if c.get("channelframes") == "sum"), chs[0])
            slave_ch  = next(
                (c for c in chs if c.get("channelframes") == "single"), None)

            # Time column: Saleae digital export uses "Time [s]" by default;
            # override per channel via optional "timeColumn" yaml field.
            time_col   = master_ch.get("timeColumn", "Time [s]")
            master_col = master_ch["name"]
            slave_col  = slave_ch["name"] if slave_ch else None

            # HAHB frames are XYE on the wire — override busType in channel_meta
            channel_meta[master_col] = {
                **channel_meta.get(master_col, {}), "busType": "xye"}
            if slave_col:
                channel_meta[slave_col] = {
                    **channel_meta.get(slave_col, {}), "busType": "xye"}

            # subtract: read from the "sum" channel entry in channels.yaml
            subtract = str(master_ch.get("subtract", "false")).lower() == "true"

            if load_and_decode_hahb is None:
                print(f"    SKIPPING HAHB {csv_name}: numpy not installed (pip install numpy)")
                continue

            try:
                master_pkts, slave_pkts = load_and_decode_hahb(
                    str(hahb_path),
                    time_col=time_col,
                    master_col=master_col,
                    slave_col=slave_col,
                    master_label=master_col,
                    slave_label=slave_col or "slave",
                    subtract=subtract,
                )
            except (ImportError, ModuleNotFoundError) as e:
                print(f"    SKIPPING HAHB {csv_name}: {e}")
                continue

            hahb_pkts = master_pkts + slave_pkts
            if hahb_pkts:
                packets.extend(hahb_pkts)
                packets.sort(key=lambda p: p["start_time"])
                print(f"[*] Merged {len(hahb_pkts)} HAHB frames from {csv_name} "
                      f"-> {len(packets)} total packets")

    write_outputs(out_path, packets, channel_meta,
                  only_pcap=args.pcap, only_csv=args.csv)


if __name__ == "__main__":
    main()
