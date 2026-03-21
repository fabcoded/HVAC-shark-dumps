# Session 2 — Session Notes (Operator Log)

Ground truth for correlating captured frames to known operator actions.
For analysis results and field encoding, see [findings.md](findings.md).

## Initial state (set before recording started)

- **Power:** ON
- **Mode:** Heat
- **Fan:** Auto
- **Temperature:** 22 deg C (set statically before the analyser was started)

Temperature was then stepped upward intentionally to provide known reference
points for decoding the IR temperature field.

---

## Pre-capture (happened before analyser started)

- Unit powered on, temp set to 22 deg C

## Not captured (happened before first recorded IR frame)

- Increase to 25 deg C
- Enable Follow Me
- Set to 26 deg C, then 27 deg C (#20/#21 in Follow-Me protocol)
- Disable Follow Me *(note: some accidental Wi-Fi hits here)*
- Set to 26 deg C

---

## Captured frames (full session — 72 IR frames)

Timestamps reference the full updated session CSV.

### t=3.0s — `B2 4D BF 40 5C A3` + D5 follow-up
- Byte 4 = 0x5C → Temp=22 deg C, bit4=1
- Note: bit4=1 at session start without a swing press —
  either the unit retained its previous swing state or bit4 encodes something else.

### t=5.6s — `B2 4D BF 40 4C B3` + D5 follow-up
- Byte 4 = 0x4C → Temp=22 deg C, bit4=0

### t=8.6s — `B2 4D BF 40 CC 33` + D5 follow-up
- Byte 4 = 0xCC → Temp=26 deg C, bit4=0

### t=23.3s — `B2 4D BF 40 DC 23` + D5 follow-up
- Byte 4 = 0xDC → Temp=26 deg C, bit4=1

### t=37.3s — `B2 4D BF 40 9C 63` + D5 follow-up
- Byte 4 = 0x9C → Temp=24 deg C, bit4=1

### t=22.38s — Frame #4  `B9 46 F7 08 00 FF` — Installer Mode param 0
### t=24.49s — Frame #6  `B9 46 F7 08 01 FE` — Installer Mode param 1
### t=26.58s — Frame #8  `B9 46 F7 08 02 FD` — Installer Mode param 2
### t=28.56s — Frame #10 `B9 46 F7 08 03 FC` — Installer Mode param 3
### t=30.87s — Frame #12 `B9 46 F7 08 04 FB` — Installer Mode param 4
### t=33.17s — Frame #14 `B9 46 F7 08 05 FA` — Installer Mode param 5
### t=35.07s — Frame #16 `B9 46 F7 08 06 F9` — Installer Mode param 6
### t=36.98s — Frame #18 `B9 46 F7 08 07 F8` — Installer Mode param 7  *(notes say "5")*
### t=38.68s — Frame #20 `B9 46 F7 08 08 F7` — Installer Mode param 8  *(notes say "4")*

- Device 0xB9 = Setup/Programming command
- Byte 2 = 0xF7 = fixed function ID for installer mode
- Byte 4 = sequential parameter index (0x00-0x08 captured)
- Each press sent as two identical repeat frames 92ms apart

> Note: session notes say params went 0->6 then back 5->1 (12 steps), but capture
> shows 9 sequential values (0-8). Discrepancy likely due to remote reliability issues
> ("it got a bit fuzzy afterwards").

### t=43.66s — Frame #22 `B9 46 F7 08 FF 00` — Settermode Query
- Byte 4 = 0xFF = settermode query command
- Post-query actions (settermode set 3, exit, set installermode 2...) not captured

### t=46.36s — Frame #24 `B2 4D BF 40 7C 83` + `D5 66 00 00 00 3B` (follow-up)
- Action: set to 24 deg C (or post-installermode AC state update)
- Byte 4 = 0x7C: bit4=1 (swing active, consistent with earlier swing-on)
- Note: byte 2 = 0xBF; session notes say "set to 24 deg C" but temp decode gives 22 deg C.
  Discrepancy unresolved — see findings.md open questions.
