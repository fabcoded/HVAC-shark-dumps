# Session 13 — Session Notes

Short unstructured session ("just some random stuff"). All control via IR remote —
app not used for active commands. Mode switching (Heat → Auto → OFF) and various
IR button presses.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 10-12
- **HAHB address**: MFB-X rotary switch at position 5 (XYE bus address 0x05)
- **Logic analyser**: Saleae
- **Wi-Fi dongle**: CONNECTED (passive — no app commands sent)
- **Wired controller**: KJR-120M
- **IR remote**: Standard Midea IR remote (Celsius mode)

---

## Initial state

- **System power**: ON
- **Mode**: Heat
- **Setpoint**: 24 C

---

## Operator action log

Reconstructed from IR frames and XYE mode transitions. Quicknote: "just some
random stuff."

| Time (s) | Action | IR frame | XYE result |
|----------|--------|----------|------------|
| 1        | Partial IR press (no repeat/D5) | B24DBF40E41B | No change |
| 19       | Mode switch to Auto | B24D**FF**00E41B | byte[8] 0x84→0x81 (Auto) |
| 129      | Unknown IR action | B24D**1F**E048B7 | No visible mode change |
| 131      | Another IR press | B24D**FF**004CB3 | byte[8] 0x81→0x94 (Auto sub) |
| 133      | Power OFF via IR | B24D**7B**84E01F | byte[8] 0x94→0x00 (OFF) |
| 140      | End of session | — | — |

---

## Session environment

- **Session duration**: ~140 s (~2.3 min)
- **Total frames captured**: 3,107 (incl. 12 IR frames)

---

## Analysis

See [findings.md](findings.md) for the full analysis results.

Key value of this session: IR byte[2] (command byte) varies across 4 distinct
values (0xBF, 0xFF, 0x1F, 0x7B), disproving the "constant 0xBF" assumption.
D5 byte[1] also varies (0x14, 0x65 vs the usual 0x66).
