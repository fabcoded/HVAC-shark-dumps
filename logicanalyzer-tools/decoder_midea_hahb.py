#!/usr/bin/env python3
"""
HAHB decoder for Midea logic analyzer captures.

Implements the independent two-track decoder strategy documented in
decoder_strategy_hahb.md.  Each track is decoded using only its own
sampled waveform; the other track is never accessed during decoding.

Bus parameters
--------------
Baud rate : 48 000 baud  (TB ≈ 20.83 µs)
Encoding  : nibble-pair Manchester-like encoding
              physical bytes → logical bytes:
              bits [0,2,4,6] of two consecutive physical bytes
              are combined into one nibble-pair and XOR'd with 0xFF
UART frame: 8N1

Decoder pipeline per track
--------------------------
1. Edge extraction from raw digital waveform
2. Burst detection  – idle > 3000 µs separates bursts
3. Glitch-tolerant burst start – first stable edge ≥ 5 µs
4. Phase search  – ±0.75 bit periods around burst start (31 steps)
5. UART 8N1 decode of sampled bit stream
6. Nibble-pair reconstruction  + XOR 0xFF
7. Candidate scoring: CRC valid > longer frame > starts with 0xAA

Post-processing (two-track mode)
---------------------------------
Slave frames that are exact duplicates of master frames (same logical
bytes, timestamp within one UART byte time) are optionally removed,
yielding a "slave-only" result.

Output
------
Standard packet dicts compatible with the HVAC_shark pcap writer:
  channel, start_time, packet_len, raw_bytes, packet_content,
  start_byte, valid_start

Frames produced by the HAHB decoder carry bus type XYE in the pcap
(set by the caller via channel_meta).

Dependencies: numpy  (pip install numpy)
"""

import csv as csvmod
from pathlib import Path

try:
    import numpy as np
except ImportError:
    raise ImportError("decoder_midea_hahb requires numpy: pip install numpy")

# ── Bus timing constants ───────────────────────────────────────────────────────
BAUD_RATE  = 48_000
TB_US      = 1_000_000 / BAUD_RATE   # bit period in µs  (≈ 20.83 µs)
IDLE_US    = 3_000                    # gap > 3000 µs → burst boundary
MIN_EDGE_US = 5.0                     # ignore glitch edges shorter than this


# ── Core decode functions ──────────────────────────────────────────────────────

def _decode_track(times_s: np.ndarray,
                  raw_signal: np.ndarray,
                  source_name: str) -> list[dict]:
    """Decode one digital track independently.

    Parameters
    ----------
    times_s     : sample timestamps in seconds
    raw_signal  : digital levels (0 / 1), same length as times_s
    source_name : label written into the 'source' field of each frame

    Returns
    -------
    List of frame dicts (including internal '_log' and '_t_us' keys used
    for duplicate removal – stripped before pcap output).
    """
    raw_signal = raw_signal.astype(np.int8)

    # Build edge list (index, timestamp_µs, level)
    diff      = np.diff(raw_signal)
    edge_idx  = np.concatenate([[0], np.where(diff != 0)[0] + 1])
    edge_t_us = times_s[edge_idx] * 1e6
    edge_lvl  = raw_signal[edge_idx]

    def sig_at(t_us: float) -> int:
        """Sample the signal at an arbitrary µs timestamp via edge table."""
        i = int(np.searchsorted(edge_t_us, t_us, side="right")) - 1
        i = max(0, min(i, len(edge_lvl) - 1))
        return 1 - int(edge_lvl[i])   # invert: wire idle = 1 → logical 1 idle

    # ── Burst detection ────────────────────────────────────────────────────────
    bursts: list[tuple[float, float]] = []
    in_burst = False
    t0_burst = None

    for k in range(len(edge_t_us) - 1):
        t   = edge_t_us[k]
        dur = edge_t_us[k + 1] - t
        lv  = 1 - int(edge_lvl[k])   # inverted logical level

        if lv == 0 and dur > IDLE_US:
            if in_burst:
                bursts.append((t0_burst, t))  # type: ignore[arg-type]
            in_burst = False
            t0_burst = None
        elif not in_burst and dur >= MIN_EDGE_US:
            t0_burst = t
            in_burst = True

    if in_burst:
        bursts.append((t0_burst, edge_t_us[-1]))  # type: ignore[arg-type]

    # ── UART decode helpers ────────────────────────────────────────────────────
    def uart_decode(bits: list[int], uart_off: int) -> list[int]:
        """Decode 8N1 bytes from a flat bit list starting at uart_off."""
        phys: list[int] = []
        i = uart_off
        while i + 9 < len(bits):
            if bits[i] != 0:       # not a start bit
                i += 1
                continue
            data = bits[i + 1:i + 9]
            if bits[i + 9] != 1:   # stop bit missing
                i += 1
                continue
            phys.append(sum(data[j] << j for j in range(8)))
            i += 10
        return phys

    def nibble_decode(phys: list[int], nib_off: int) -> list[int]:
        """Reconstruct logical bytes from physical byte pairs.

        Each logical byte is formed from bits [0,2,4,6] of two consecutive
        physical bytes, then XOR'd with 0xFF.
        """
        src = phys[nib_off:]
        out: list[int] = []
        for i in range(0, len(src) - 1, 2):
            a, b = src[i], src[i + 1]
            na = (
                ((a >> 0) & 1)
                | (((a >> 2) & 1) << 1)
                | (((a >> 4) & 1) << 2)
                | (((a >> 6) & 1) << 3)
            )
            nb = (
                ((b >> 0) & 1)
                | (((b >> 2) & 1) << 1)
                | (((b >> 4) & 1) << 2)
                | (((b >> 6) & 1) << 3)
            )
            out.append((nb | (na << 4)) ^ 0xFF)
        return out

    # ── Per-burst phase search & scoring ──────────────────────────────────────
    frames: list[dict] = []

    for bi, (t0, t1) in enumerate(bursts):
        best: dict | None = None

        for phase_us in np.linspace(-0.75 * TB_US, 0.75 * TB_US, 31):
            start = t0 + phase_us
            nbits = int(max(0, t1 - start) / TB_US) + 24
            if nbits < 20:
                continue

            bits = [sig_at(start + k * TB_US) for k in range(nbits)]

            for uart_off in range(10):
                phys = uart_decode(bits, uart_off)
                if len(phys) < 2:
                    continue

                for nib_off in (0, 1):
                    logical = nibble_decode(phys, nib_off)
                    if len(logical) < 3:
                        continue

                    crc_calc = (-sum(logical[1:-1])) % 256
                    crc_ok   = crc_calc == logical[-1]
                    first_aa = int(logical[0] == 0xAA)
                    score    = (int(crc_ok), len(logical), first_aa)

                    cand = {
                        "score":       score,
                        "source":      source_name,
                        "burst_idx":   bi,
                        "timestamp_s": round(t0 / 1e6, 9),
                        "phase_us":    round(float(phase_us), 3),
                        "uart_off":    int(uart_off),
                        "nib_off":     int(nib_off),
                        "cmd":         f"{logical[1]:02X}" if len(logical) > 1 else "",
                        "len":         len(logical),
                        "crc_ok":      bool(crc_ok),
                        "crc_calc":    f"{crc_calc:02X}",
                        "frame_hex":   " ".join(f"{v:02X}" for v in logical),
                        # internal fields – not written to pcap
                        "_log":  logical,
                        "_t_us": t0,
                    }

                    if best is None or cand["score"] > best["score"]:
                        best = cand

        if best is not None:
            frames.append(best)

    return frames


# ── Conversion to packet dicts ─────────────────────────────────────────────────

def _frames_to_packets(frames: list[dict], channel_name: str) -> list[dict]:
    """Convert HAHB frame dicts to standard packet dicts for pcap writing."""
    packets: list[dict] = []
    for f in frames:
        raw_bytes = f.get("_log", [])
        if not raw_bytes:
            continue
        start_byte = raw_bytes[0]
        packets.append({
            "channel":        channel_name,
            "start_time":     f["timestamp_s"],
            "packet_len":     len(raw_bytes),
            "raw_bytes":      raw_bytes,
            "packet_content": " ".join(f"{b:02X}" for b in raw_bytes),
            "start_byte":     f"0x{start_byte:02X}",
            "valid_start":    start_byte == 0xAA and f.get("crc_ok", False),
        })
    return packets


# ── Public API ────────────────────────────────────────────────────────────────

def load_and_decode_hahb(
    input_csv: str,
    time_col: str = "time",
    master_col: str | None = None,
    slave_col:  str | None = None,
    master_label: str = "master",
    slave_label:  str = "slave",
    subtract: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Load a Saleae digital export CSV and decode HAHB frames.

    Parameters
    ----------
    input_csv    : path to the digital waveform CSV
    time_col     : name of the timestamp column (default "time")
    master_col   : column name for the master / bus signal
    slave_col    : column name for the slave signal  (optional)
    master_label : channel label used in output packets for master
    slave_label  : channel label used in output packets for slave
    subtract     : if True, remove from slave packets any frames that are
                   exact duplicates of master frames (same bytes, timestamp
                   within one UART byte period)

    Returns
    -------
    (master_packets, slave_packets)
    Each element is a list of standard packet dicts.
    slave_packets is empty when slave_col is None.
    """
    import pandas as pd

    df = pd.read_csv(input_csv)
    times = df[time_col].to_numpy()

    master_packets: list[dict] = []
    slave_packets:  list[dict] = []
    master_frames:  list[dict] = []

    if master_col:
        if master_col not in df.columns:
            raise ValueError(
                f"Column '{master_col}' not found in {input_csv}. "
                f"Available: {list(df.columns)}"
            )
        print(f"[*] HAHB decode: master '{master_col}' → '{master_label}'")
        master_frames = _decode_track(times, df[master_col].to_numpy(), master_label)
        crc_ok = sum(1 for f in master_frames if f["crc_ok"])
        print(f"    {len(master_frames)} frames  ({crc_ok} CRC-OK)")
        master_packets = _frames_to_packets(master_frames, master_label)

    if slave_col:
        if slave_col not in df.columns:
            raise ValueError(
                f"Column '{slave_col}' not found in {input_csv}. "
                f"Available: {list(df.columns)}"
            )
        print(f"[*] HAHB decode: slave  '{slave_col}' → '{slave_label}'")
        slave_frames = _decode_track(times, df[slave_col].to_numpy(), slave_label)
        crc_ok = sum(1 for f in slave_frames if f["crc_ok"])
        print(f"    {len(slave_frames)} frames  ({crc_ok} CRC-OK)")

        if subtract and master_frames:
            byte_time_us = 10 * TB_US
            filtered = [
                f for f in slave_frames
                if not any(
                    abs(f["_t_us"] - mf["_t_us"]) <= byte_time_us
                    and f["_log"] == mf["_log"]
                    for mf in master_frames
                )
            ]
            removed = len(slave_frames) - len(filtered)
            print(f"    Subtracted {removed} master-duplicate frames "
                  f"→ {len(filtered)} slave-only frames")
            slave_frames = filtered

        slave_packets = _frames_to_packets(slave_frames, slave_label)

    return master_packets, slave_packets
