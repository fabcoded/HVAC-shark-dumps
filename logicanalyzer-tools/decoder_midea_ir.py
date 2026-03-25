#!/usr/bin/env python3
"""
IR raw pulse-width decoder for Midea logic analyzer captures.

Decodes NEC-like IR frames from raw signal transitions exported by Saleae
(Time [s] / channel-level CSV).

Timing convention: active-low (TSOP receiver output).
  - 0 = mark (IR burst active)
  - 1 = space (idle)

Frame structure: ~4.4 ms header mark + ~4.4 ms header space + 48 data bits + stop mark.
Validation: each data byte must be the bitwise complement of the following byte
(standard NEC complement check, applied to all three byte pairs).

Output: list of packet dicts compatible with write_pcap / write_csv.
"""

import csv as csvmod
from pathlib import Path

IR_HEADER_MARK_MIN  = 0.003   # header mark  > 3 ms
IR_HEADER_SPACE_MIN = 0.003   # header space > 3 ms
IR_BIT_SPACE_THRESH = 0.001   # space > 1 ms → bit 1, else bit 0
IR_BITS_PER_FRAME   = 48      # 6 bytes per frame


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
    """Decode NEC-like IR frames from raw signal transitions."""
    packets: list[dict] = []
    i = 0
    n = len(transitions)

    while i < n - 4:
        # Wait for mark start (level 0)
        if transitions[i][1] != 0:
            i += 1
            continue

        # Header mark: must end at level 1
        if transitions[i + 1][1] != 1:
            i += 1
            continue
        mark_dur = transitions[i + 1][0] - transitions[i][0]
        if mark_dur < IR_HEADER_MARK_MIN:
            i += 1
            continue

        # Header space: must end at level 0
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
        j = i + 2  # points to first data-bit mark (level 0)

        while j + 2 < n and len(bits) < IR_BITS_PER_FRAME:
            if transitions[j][1] != 0:
                break
            space_start = transitions[j + 1][0]
            next_mark   = transitions[j + 2][0]
            bit_space   = next_mark - space_start
            if bit_space > 0.005:   # too long → not a data bit
                break
            bits.append(1 if bit_space > IR_BIT_SPACE_THRESH else 0)
            j += 2

        if len(bits) == IR_BITS_PER_FRAME:
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
                "channel":        channel_name,
                "start_time":     frame_start_time,
                "packet_len":     len(raw_bytes),
                "raw_bytes":      raw_bytes,
                "packet_content": " ".join(f"{b:02X}" for b in raw_bytes),
                "start_byte":     f"0x{raw_bytes[0]:02X}",
                "valid_start":    complement_ok,
            })

        i = j

    return packets


def load_and_decode_ir_channels(config: dict, session_dir: Path) -> list[dict]:
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
