#!/usr/bin/env python3
"""
Community Frame YAML → pcap Converter

Converts YAML files containing manually documented XYE/UART frames
(e.g. from Home Assistant community posts, forum captures) into
Wireshark-readable pcap files using the HVAC_shark v2 framing.

Each session within a YAML file produces a separate pcap file.

Input YAML layout:
  sessions:
    - session: <name>
      description: ...
      frames:
        - raw: "AA:C0:00:..."
          dir: master_to_unit | unit_to_master
          description: ...

Output:  <output_dir>/<session_name>.pcap

Timing: synthetic — 100 ms between frames within a session.
"""

import argparse
import struct
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Reuse HVAC_shark framing from the main converter
from logic_analyzer_midea_to_pcap import (
    build_hvac_shark_payload,
    _build_frame,
    PCAP_MAGIC,
    LINKTYPE_ETHERNET,
)

FRAME_SPACING_S = 0.100  # 100 ms between frames



def load_yaml(path: str) -> dict:
    """Load a capture YAML file."""
    if yaml is not None:
        with open(path) as f:
            return yaml.safe_load(f)
    else:
        print("ERROR: PyYAML required — pip install pyyaml", file=sys.stderr)
        sys.exit(1)


def parse_raw_hex(raw: str) -> list[int]:
    """Parse hex string like 'AA:C0:00:...' or 'AA C0 00 ...' into byte list."""
    raw = raw.strip()
    if ":" in raw:
        parts = raw.split(":")
    else:
        parts = raw.split()
    return [int(b, 16) for b in parts]


def write_session_pcap(filepath: str, frames: list[dict],
                       source_name: str, bus_type: str = "xye"):
    """Write a single session's frames to a pcap file."""
    with open(filepath, "wb") as f:
        # pcap global header
        f.write(struct.pack("<IHHiIII",
            PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_ETHERNET))

        for i, frame in enumerate(frames):
            raw_hex = frame.get("raw", "")
            if not raw_hex:
                continue

            raw_bytes = parse_raw_hex(raw_hex)

            # Direction — pass through as-is from YAML, no mapping
            direction = frame.get("dir", "")
            comment = f"[{direction}]" if direction else ""

            # Channel name = source contributor name
            channel_name = source_name

            hvac_payload = build_hvac_shark_payload(
                raw_bytes,
                channel_name=channel_name,
                circuit_board="",
                comment=comment,
                bus_type=bus_type,
            )

            # Synthetic src_port: differentiate by direction string
            src_port = 10001 + (i % 2)
            eth_frame = _build_frame(hvac_payload, src_port)

            # Synthetic timestamp: 100ms spacing
            ts = i * FRAME_SPACING_S
            ts_sec = int(ts)
            ts_usec = int((ts - ts_sec) * 1_000_000)

            f.write(struct.pack("<IIII", ts_sec, ts_usec,
                                len(eth_frame), len(eth_frame)))
            f.write(eth_frame)


def main():
    parser = argparse.ArgumentParser(
        description="Convert community frame YAML files to pcap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s captures/rymo-static-pressure.yaml
  %(prog)s captures/rymo-static-pressure.yaml -o output_dir/
  %(prog)s captures/*.yaml
""")
    parser.add_argument("yaml_files", nargs="+",
        help="One or more YAML capture files")
    parser.add_argument("-o", "--output-dir",
        help="Output directory for pcap files (default: same dir as YAML)")
    parser.add_argument("--bus-type", default="xye",
        help="Bus type for frames (default: xye)")

    args = parser.parse_args()

    for yaml_path in args.yaml_files:
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            print(f"ERROR: {yaml_path} not found", file=sys.stderr)
            continue

        print(f"[*] Loading: {yaml_path}")
        doc = load_yaml(str(yaml_path))

        sessions = doc.get("sessions", [])
        if not sessions:
            print(f"    No sessions found in {yaml_path.name}")
            continue

        # Extract source name from top-level YAML field, or parent folder name
        source_name = doc.get("source_name", yaml_path.parent.name)

        out_dir = Path(args.output_dir) if args.output_dir else yaml_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        for sess in sessions:
            sess_name = sess.get("session", "unknown")
            sess_idx = sess.get("session_index", "")
            frames = sess.get("frames", [])
            if not frames:
                print(f"    Session '{sess_name}': no frames, skipping")
                continue

            if sess_idx:
                pcap_path = out_dir / f"session_{sess_idx}.pcap"
            else:
                pcap_path = out_dir / f"session_{sess_name}.pcap"
            write_session_pcap(
                str(pcap_path), frames,
                source_name=source_name,
                bus_type=args.bus_type,
            )
            print(f"    Session '{sess_name}': {len(frames)} frames -> {pcap_path}")

    print("[ok] Done")


if __name__ == "__main__":
    main()
