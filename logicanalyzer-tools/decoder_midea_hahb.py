#!/usr/bin/env python3
"""
HAHB decoder for Midea logic analyzer captures.

Overview
--------
The HAHB (High-speed AC High-frequency Bus) is a proprietary Midea RS-485
bus running at 48 000 baud.  It carries XYE-framed packets and is tapped
directly at the RS-485 transceiver chip on the adapter board.  Because the
bus is half-duplex, a two-channel capture (one probe per transceiver
differential pair) yields both the combined bus signal and, optionally, a
single-direction view; the decoder can process either one track or both
independently.

Physical / encoding parameters
--------------------------------
  Baud rate  : 48 000 baud  (TB ≈ 20.83 µs per bit)
  UART frame : 8N1 (1 start bit, 8 data bits, 1 stop bit = 10 bit-periods)
  Line idle  : logic 1 (inverted in the decoder so idle = 0 for burst logic)
  Encoding   : nibble-pair encoding
                 Two consecutive physical UART bytes encode one logical byte.
                 Bits [0, 2, 4, 6] are extracted from each physical byte,
                 combined into a nibble pair, then XOR'd with 0xFF:
                   na = phys_a bits [0,2,4,6]
                   nb = phys_b bits [0,2,4,6]
                   logical = (nb | (na << 4)) ^ 0xFF

Decoder pipeline (per track, fully independent)
------------------------------------------------
Each track is decoded using only its own sampled waveform.  No information
from the other track is accessed during decoding of a given track.

  Step 1 – Edge extraction
    A compact edge list is built from transitions in the raw digital input.
    Only transition timestamps are stored; the raw sample array is not kept
    in memory during decoding.  This edge list is the sole timing source for
    the track.

  Step 2 – Burst detection
    The edge list is scanned for idle regions.  After signal inversion
    (so that the idle state maps to logical 0), any gap longer than
    IDLE_US = 3 000 µs is treated as a burst boundary.  Each contiguous
    active segment is collected as a (t_start, t_end) burst.

  Step 3 – Glitch-tolerant burst start
    Within a burst, the decoder only starts sampling at the first edge
    segment of at least MIN_EDGE_US = 5 µs.  Very short transitions at the
    beginning of some bursts (glitches from bus arbitration or probe
    coupling) are ignored.

  Step 4 – Phase search
    For each burst, 31 evenly spaced sampling phases are tested in the range
    [-0.75 × TB, +0.75 × TB] µs around the burst start.  This compensates
    for sub-bit start misalignment without using any cross-track information.
    The signal is sampled by looking up the edge table at each bit centre.

  Step 5 – UART 8N1 decoding
    For each phase candidate, all 10 possible UART bit offsets (0–9) are
    tested.  For each offset, the sampled bit stream is scanned for valid
    8N1 frames: a 0 start bit followed by 8 data bits followed by a 1 stop
    bit.  Each valid frame contributes one physical byte.

  Step 6 – Logical byte reconstruction
    For each UART decode result and each nibble-pair alignment offset
    (0 or 1), the nibble-pair encoding is reversed to recover the logical
    byte sequence.

  Step 7 – Candidate scoring
    All (phase, uart_off, nib_off) candidates for a burst are ranked by a
    three-key score, evaluated using only local evidence from the same track:
      1. CRC valid   — two's-complement checksum over logical[1..-2]
                       matches logical[-1]   (highest priority)
      2. Frame length — longer decoded frames preferred
      3. Preamble    — logical[0] == 0xAA preferred

    The highest-scoring candidate is kept as the burst's decoded frame.

Post-processing – directional separation (two-track mode, subtract=True)
-------------------------------------------------------------------------
After both tracks are decoded independently, master (sum) frames that also
appear in slave (single) are removed from master.  A match is declared when:
  - the decoded logical bytes are identical, and
  - the burst timestamps differ by no more than one UART byte time
    (10 × TB ≈ 208 µs) to absorb jitter between the two probe points.

Result:
  master_out = master − slave  →  the direction slave does NOT see
  slave_out  = slave as-is     →  the direction slave DOES see

Together the two output channels separate both RS-485 directions cleanly
without duplicates, despite the jitter between the sum and single probes.

Internal frame dict fields (produced by _decode_track)
-------------------------------------------------------
  source      : track label passed by caller
  burst_idx   : index of the burst within the track
  timestamp_s : burst start time in seconds
  phase_us    : winning sampling phase offset in µs
  uart_off    : winning UART bit offset (0–9)
  nib_off     : winning nibble-pair alignment offset (0 or 1)
  cmd         : logical[1] as hex string (XYE command byte)
  len         : number of logical bytes decoded
  crc_ok      : True if CRC check passed
  crc_calc    : expected CRC byte as hex string
  frame_hex   : full logical frame as space-separated hex
  _log        : logical byte list  (internal – not written to pcap)
  _t_us       : burst start time in µs  (internal – used for deduplication)

Output packet dicts (produced by _frames_to_packets / load_and_decode_hahb)
----------------------------------------------------------------------------
Standard dicts compatible with the HVAC_shark pcap writer:
  channel, start_time, packet_len, raw_bytes, packet_content,
  start_byte, valid_start

HAHB frames carry bus type XYE in the HVAC_shark header (set by the caller
via channel_meta when calling write_pcap).

Dependencies
------------
  numpy   (pip install numpy)
  pandas  (pip install pandas)  — used only in load_and_decode_hahb
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
    """Run the full 7-step HAHB decode pipeline on one digital track.

    The track is decoded using only its own waveform (no cross-track access).
    See the module docstring for a detailed description of each step.

    Returns a list of frame dicts; fields prefixed with '_' are internal and
    are stripped before pcap output.
    """
    raw_signal = raw_signal.astype(np.int8)

    # Step 1 – Edge extraction: build compact (timestamp_µs, level) edge table.
    diff      = np.diff(raw_signal)
    edge_idx  = np.concatenate([[0], np.where(diff != 0)[0] + 1])
    edge_t_us = times_s[edge_idx] * 1e6
    edge_lvl  = raw_signal[edge_idx]

    def sig_at(t_us: float) -> int:
        """Look up signal level at t_us via binary search on the edge table."""
        i = int(np.searchsorted(edge_t_us, t_us, side="right")) - 1
        i = max(0, min(i, len(edge_lvl) - 1))
        return 1 - int(edge_lvl[i])   # invert: wire idle=1 → logical idle=0

    # Step 2 – Burst detection: idle > IDLE_US µs separates bursts.
    # Step 3 – Glitch-tolerant start: first stable edge ≥ MIN_EDGE_US µs.
    bursts: list[tuple[float, float]] = []
    in_burst = False
    t0_burst = None

    for k in range(len(edge_t_us) - 1):
        t   = edge_t_us[k]
        dur = edge_t_us[k + 1] - t
        lv  = 1 - int(edge_lvl[k])   # inverted logical level

        if lv == 0 and dur > IDLE_US:          # long idle → burst end
            if in_burst:
                bursts.append((t0_burst, t))   # type: ignore[arg-type]
            in_burst = False
            t0_burst = None
        elif not in_burst and dur >= MIN_EDGE_US:  # stable edge → burst start
            t0_burst = t
            in_burst = True

    if in_burst:
        bursts.append((t0_burst, edge_t_us[-1]))  # type: ignore[arg-type]

    # Step 5 helper – UART 8N1: scan bit stream for valid start+data+stop triples.
    def uart_decode(bits: list[int], uart_off: int) -> list[int]:
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

    # Step 6 helper – Nibble-pair decode: bits [0,2,4,6] of each physical byte
    # pair → one logical byte, XOR 0xFF.
    def nibble_decode(phys: list[int], nib_off: int) -> list[int]:
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

    # Steps 4 + 5 + 6 + 7 – Phase search, UART decode, nibble decode, scoring.
    frames: list[dict] = []

    for bi, (t0, t1) in enumerate(bursts):
        best: dict | None = None

        # Step 4: test 31 phases spanning ±0.75 bit periods
        for phase_us in np.linspace(-0.75 * TB_US, 0.75 * TB_US, 31):
            start = t0 + phase_us
            nbits = int(max(0, t1 - start) / TB_US) + 24
            if nbits < 20:
                continue

            bits = [sig_at(start + k * TB_US) for k in range(nbits)]

            # Step 5: all 10 possible UART bit offsets
            for uart_off in range(10):
                phys = uart_decode(bits, uart_off)
                if len(phys) < 2:
                    continue

                # Step 6: both nibble-pair alignments
                for nib_off in (0, 1):
                    logical = nibble_decode(phys, nib_off)
                    if len(logical) < 3:
                        continue

                    # Step 7: score by (CRC valid, frame length, 0xAA preamble)
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
                        "_log":        logical,   # internal – used for dedup
                        "_t_us":       t0,        # internal – used for dedup
                    }

                    if best is None or cand["score"] > best["score"]:
                        best = cand

        if best is not None:
            frames.append(best)

    return frames


# ── Conversion to packet dicts ─────────────────────────────────────────────────

def _frames_to_packets(frames: list[dict], channel_name: str) -> list[dict]:
    """Convert HAHB frame dicts to standard packet dicts for pcap writing.

    HAHB frames are XYE frames without the RS-485 end-of-frame byte (0x55).
    The Wireshark dissector expects 16-byte requests and 32-byte responses
    (i.e. standard XYE with 0x55 appended).  Because 0xAA + 0x55 = 0xFF ≡ -1
    (mod 256), appending 0x55 does not invalidate the two's-complement CRC:
      HAHB CRC = (-sum(bytes[1:-1])) % 256
      XYE  CRC = (255 - (sum(bytes[0:-2]) + 0x55)) % 256
               = (255 - (0xAA + sum(bytes[1:-2]) + 0x55)) % 256
               = (255 - (0xFF + sum(bytes[1:-2]))) % 256
               = (-sum(bytes[1:-2])) % 256  ← identical
    So 0x55 is appended unconditionally to every decoded HAHB frame.
    """
    packets: list[dict] = []
    for f in frames:
        raw_bytes = f.get("_log", [])
        if not raw_bytes:
            continue
        # Restore the XYE end-of-frame epilogue stripped by the HAHB bus
        raw_bytes = list(raw_bytes) + [0x55]
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
                   In a two-probe HAHB capture this is the "sum" channel
                   (directly on the RS-485 bus — sees all traffic from both
                   directions).
    slave_col    : column name for the slave signal  (optional)
                   In a two-probe HAHB capture this is the "single" channel
                   (one side of the transceiver — sees only one direction).
    master_label : channel label used in output packets for master
    slave_label  : channel label used in output packets for slave
    subtract     : if True, remove from master (sum) any frames that also
                   appear in slave (single), leaving only the direction that
                   slave does NOT see.
                   master_out = master − slave  (the "other" direction)
                   slave_out  = slave as-is      (the "single" direction)
                   Together the two outputs cleanly separate both directions
                   without duplicates.

    Returns
    -------
    (master_packets, slave_packets)
    Each element is a list of standard packet dicts.
    slave_packets is empty when slave_col is None.
    """
    import pandas as pd

    df = pd.read_csv(input_csv)
    times = df[time_col].to_numpy()

    master_frames: list[dict] = []
    slave_frames:  list[dict] = []

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

    # subtract=True: remove from master (sum) every frame that also appears
    # in slave (single).  Jitter tolerance: timestamps may differ by up to
    # one full UART byte time (10 bit-periods).
    if subtract and master_frames and slave_frames:
        byte_time_us = 10 * TB_US
        filtered = [
            f for f in master_frames
            if not any(
                abs(f["_t_us"] - sf["_t_us"]) <= byte_time_us
                and f["_log"] == sf["_log"]
                for sf in slave_frames
            )
        ]
        removed = len(master_frames) - len(filtered)
        print(f"    Subtracted {removed} slave-matched frames from master "
              f"→ {len(filtered)} master-unique frames")
        master_frames = filtered

    return (
        _frames_to_packets(master_frames, master_label),
        _frames_to_packets(slave_frames,  slave_label),
    )
