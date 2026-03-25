#!/usr/bin/env python3
"""
Serial byte-stream decoder for Midea logic analyzer captures.

Handles Saleae-style CSV exports where each row is a UART-decoded byte.
Groups bytes into packets using inter-byte gap detection.

Input CSV columns expected: name, type, start_time, duration, data
Output: list of packet dicts compatible with write_pcap / write_csv.
"""

import csv as csvmod
import statistics
from collections import defaultdict

GAP_MULTIPLIER    = 5
VALID_START_BYTES = {0xAA, 0x55}


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


def _flush(packets: list, recs: list[dict], channel: str,
           start: int, end: int):
    pkt_bytes = [recs[i]["byte_val"] for i in range(start, end + 1)]
    if not pkt_bytes:
        return
    start_byte = pkt_bytes[0]
    packets.append({
        "channel":        channel,
        "start_time":     recs[start]["start_time"],
        "packet_len":     len(pkt_bytes),
        "raw_bytes":      pkt_bytes,
        "packet_content": " ".join(f"{b:02X}" for b in pkt_bytes),
        "start_byte":     f"0x{start_byte:02X}",
        "valid_start":    start_byte in VALID_START_BYTES,
    })


def extract_packets(records: list[dict],
                    gap_multiplier: float = GAP_MULTIPLIER) -> list[dict]:
    """Group bytes into packets per channel using inter-byte gap detection."""
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
