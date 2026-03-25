# Session 5 — Session Notes (Operator Log)

Ground truth for correlating captured frames to known hardware setup and context.
For analysis results, see findings.md (not yet written).

---

## Hardware under test

- **Unit**: Midea extremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Session 4 — all internal display board buses simultaneously:
  HAHB RS-485 transceiver (adapter board), R/T CN1 bidirectional,
  Wi-Fi module CN3 UART, mainboard UART CN1 grey/blue
- **Logic analyser**: Saleae

---

## Probe setup

Same channel configuration as Session 4. See [Session 4 channels.yaml](../Session%204/channels.yaml)
as the reference; copy or symlink as appropriate.

---

## Follow-Me configuration

- **Active throughout the session**: yes
- **Sensor source**: KJR-12x internal (display) sensor — same as Session 4
- **KJR-12x display reading at session start**: approx. **11 °C** (controller is outside)
- **KJR-12x display reading during session**: drops to approx. **10 °C**
- **Indoor unit sensor (estimated)**: approx. **15 °C** (unit remains indoors)

> The controller was physically moved outside between Session 4 and Session 5.
> This creates a deliberate temperature split: the Follow-Me sensor (KJR-12x internal)
> reads a lower temperature than the indoor unit's own sensors.

---

## Initial state (at capture start)

- **System power**: ON (running from prior session — no cold-start this session)
- **Mode**: Heat (unchanged throughout)
- **Setpoint**: 25 °C (carry-over from end of Session 4)
- **Fan**: Auto

---

## Operator action sequence

Timing is approximate — exact timestamps are derivable from the capture.

| Step | Action                                    | Expected state after        |
|------|-------------------------------------------|-----------------------------|
| 1    | Recording started with system running     | Heat/Auto/25 °C, Follow-Me ~11 °C |
| 2    | Setpoint decreased: 25 °C → 24 °C        | Heat/Auto/24 °C             |
| 3    | Setpoint decreased: 24 °C → 23 °C        | Heat/Auto/23 °C             |
| 4    | Setpoint decreased: 23 °C → 22 °C        | Heat/Auto/22 °C             |
| 5    | Setpoint increased: 22 °C → 23 °C        | Heat/Auto/23 °C             |
| 6    | (passive observation until end of capture) | Heat/Auto/23 °C           |

---

## Key analysis opportunities in this session

- **Follow-Me temperature confirmation**: KJR-12x sensor starts at ~11 °C and drops to ~10 °C.
  In the R-T 0x41 query body[5] the expected values are:
  - 11 °C → `11 × 2 + 50 = 72 = 0x48`
  - 10 °C → `10 × 2 + 50 = 70 = 0x46`
  If body[5] tracks from 0x48 → 0x46 during the session, this confirms the field identity
  established in Session 4 (body[5] = T×2+50) independent of the 13 °C fixed value.

- **Indoor vs Follow-Me temperature split**: The indoor unit's own sensors read ~15 °C
  (expected raw: `15 × 2 + 50 = 80 = 0x50`). Session 4 showed body[11] of the 0xC0 response
  tracking the Follow-Me value, not the unit's own sensor. This session tests whether the
  split is visible — 0xC0 body[11] should still follow the KJR-12x value (0x48/0x46),
  not the indoor sensor value (0x50).

- **Setpoint progression going downward**: Session 4 only captured ascending setpoints
  (22→23→24→25 °C). This session captures 25→24→23→22→23 °C, exercising the same
  XYE/R-T encoding in the opposite direction. Confirms T+0x40 hypothesis for: 0x59 (25),
  0x58 (24), 0x57 (23), 0x56 (22).

- **C6 Follow-Me handshake**: Expect C6 pairs at each setpoint step. byte[18] should track
  0x59→0x58→0x57→0x56→0x57. byte[17] (fan) should remain 0x80 (Auto) throughout.

---

## Open questions this session should address

- Does R-T 0x41 query body[5] change from 0x48 → 0x46 as the KJR-12x display drops
  from 11 °C to 10 °C? (Confirms body[5] as the Follow-Me room temperature field.)
- Does 0xC0 response body[11] follow the KJR-12x sensor (0x48/0x46) or the indoor
  unit sensor (~0x50)? (Establishes which temperature source the mainboard uses for
  Follow-Me control.)
- Do XYE C3 frames still carry setpoint in byte[8] (not room temperature)?
  Expected values: 0x59/0x58/0x57/0x56 tracking the operator steps.
