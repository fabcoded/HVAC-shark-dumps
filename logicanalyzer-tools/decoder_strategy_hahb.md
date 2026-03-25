# Independent two-track decoder

## Purpose
This decoder processes channel 6 and channel 7 independently and writes three CSV files:
- `ch6_independent.csv`
- `ch7_independent.csv`
- `ch6_minus_ch7_independent.csv`

The subtraction step is applied only after both channels have been decoded completely.

## Decoder strategy

### 1. Fully independent per-track decoding
Each track is decoded using only its own sampled waveform. During decoding of CH6, the CH7 waveform is never accessed. During decoding of CH7, the CH6 waveform is never accessed.

### 2. Edge extraction
For the selected track, the decoder builds an edge list from transitions in the raw digital input. This edge list is used as the only timing source for that track.

### 3. Burst detection
Bursts are separated by long idle periods. Idle is detected after inversion of the selected track, and a region longer than 3000 us is treated as a burst boundary.

### 4. Glitch-tolerant burst start
A burst starts at the first stable edge segment of at least 5 us. This suppresses very short glitch-like transitions at the beginning of some bursts.

### 5. Phase search
For each burst, the decoder searches a phase window around the burst start from -0.75 bit periods to +0.75 bit periods. This compensates for sub-bit start misalignment without using any information from the other track.

### 6. UART decoding
For each phase candidate, the sampled bitstream is decoded as 8N1 UART. All 10 UART bit offsets are tested and each valid physical byte sequence is collected.

### 7. Logical byte reconstruction
Logical protocol bytes are reconstructed from pairs of physical bytes. The decoder extracts bits [0,2,4,6] from each physical byte, combines them into one nibble pair, and applies XOR 0xFF.

### 8. Candidate scoring
All candidates are scored using only local evidence from the same track:
1. CRC valid is preferred.
2. Longer decoded frames are preferred.
3. Frames starting with 0xAA are preferred.

### 9. Post-processing subtraction
After both tracks are decoded, exact duplicate CH7 frames are removed from CH6 when:
- the decoded logical bytes are identical, and
- the timestamps differ by no more than one byte time.

The result is written as `ch6_minus_ch7_independent.csv`.

## Extensions in this version
- Unified decoder for both tracks.
- Strict track independence during decode.
- Stable-edge burst start detection.
- Burst-local phase search.
- Automatic CSV export for all three result sets.
- Duplicate removal applied only after both tables are complete.

## Output columns
- `source`: frame source label
- `burst_idx`: burst number inside the channel
- `timestamp_s`: burst start timestamp in seconds
- `phase_us`: selected sampling phase relative to burst start
- `uart_off`: selected UART bit offset
- `nib_off`: selected nibble-pair offset
- `cmd`: second logical byte as command code
- `len`: decoded logical frame length in bytes
- `crc_ok`: CRC validation result
- `crc_calc`: calculated CRC byte
- `frame_hex`: decoded logical frame bytes in hexadecimal

## Expected result on the current capture
- CH6: 127 frames, all CRC valid
- CH7: 45 frames, all CRC valid
- CH6 minus CH7: 82 frames, all CRC valid
- Removed duplicates: 45 frames
