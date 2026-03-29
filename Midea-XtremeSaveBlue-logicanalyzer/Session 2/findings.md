# Session 2 — Findings

## Session context

First IR capture session on the Midea XtremeSaveBlue display board.
Key discovery: the Midea remote control uses a **NEC-like IR protocol** with
48-bit frames (6 bytes), complement integrity pairs, and pulse-width encoding.
Three device IDs were observed: `0xB2` (AC control), `0xB9` (installer/setter mode),
`0xD5` (follow-up frame).

For the operator action log and raw frame timestamps, see [SessionNotes.md](SessionNotes.md).
For the full IR protocol reference, see
[protocol_ir.md](../../../../HVAC-shark/protocol-analysis/protocol_ir.md).

---

## Field encoding observations

Cross-referenced against 72 IR frames (16 B2 AC frames with 5 distinct byte4 values).

| Field              | Byte | Bits  | Encoding                                    | Confidence      |
|--------------------|------|-------|---------------------------------------------|-----------------|
| Device type        | 0    | [7:0] | 0xB2=AC, 0xB9=Setup, 0xD5=Follow-up        | Confirmed       |
| Complement pairs   | 1,3,5| [7:0] | ~byte[n-1] & 0xFF (except 0xD5 pair)       | Confirmed       |
| Temperature        | 4    | [7:5] | bits[7:5] + 20 = deg C                     | 3 data points   |
| Fixed marker       | 4    | [3:0] | Always 0xC in all captured frames           | Observed        |
| bit4 / swing?      | 4    | [4]   | Toggles between frames; meaning unclear     | Uncertain       |
| Mode / power flags | 2    | [7:0] | 0xBF = Heat + Auto fan; bit layout TBD     | Partial         |
| B9 function ID     | 2    | [7:0] | 0xF7 = installer/setter mode                | Observed        |
| B9 parameter       | 4    | [7:0] | Index 0x00-0x08; 0xFF = settermode query   | Observed        |
| Follow-up payload  | 2-5  | all   | 0x00 0x00 0x00 0x3B (fixed)                | Observed        |

### Temperature — confirmed data points

| byte[4] | bits[7:5] | Decoded  | Known action            |
|---------|-----------|----------|-------------------------|
| `0x5C`  | 2         | 22 deg C | Initial state           |
| `0x4C`  | 2         | 22 deg C | Confirmed               |
| `0xCC`  | 6         | 26 deg C | Stepped up twice        |
| `0xDC`  | 6         | 26 deg C | Confirmed               |
| `0x9C`  | 4         | 24 deg C | Stepped down            |

---

## Open questions

### 1. byte[4] bit[4] — vertical swing or something else?

Bit 4 was already set at session start (t=3.0s) without an explicit swing press.
It toggles between consecutive B2 frames without a corresponding user action.

Possible interpretations:
- Vertical swing state retained from the remote's internal state
- A different feature (horizontal swing, display brightness, feature-enable flag)

**To resolve**: capture a session toggling vertical swing ON and OFF with no other
changes, and observe which bit changes.

### 2. byte[2] = 0xBF — mode and fan bit layout

Constant across all B2 frames in this session (Heat + Auto fan only).
Individual bit assignments for mode and fan speed are unknown.

**To resolve**: capture mode switching (Cool / Heat / Dry / Fan) and fan speed
changes (Auto / High / Medium / Low).

### 3. Temperature encoding range

Confirmed for 22, 24, 26 deg C only. Formula `bits[7:5] + 20` gives a maximum of
27 deg C with 3 bits — unclear how temperatures above 27 deg C or below 20 deg C
are encoded.

**To resolve**: capture sessions at 16 deg C (Midea minimum) and 30 deg C (maximum).

### 4. Frame #24 temperature discrepancy

Session notes say "set to 24 deg C" at t=46.36s, but byte[4]=0x7C decodes to
22 deg C (bits[7:5]=3, 3+20=23 — actually 23 deg C, not matching either value).
Either the temperature was not changed by this press (post-installer-mode state
restore) or the encoding breaks after installer mode interaction.

**To resolve**: repeat the sequence with explicit temperature steps and no installer
mode interaction in between.
