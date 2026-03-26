# Session 4 — Session Notes (Operator Log)

Ground truth for correlating captured frames to known hardware setup and context.
For analysis results, see findings.md (not yet written).

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: All internal display board buses simultaneously —
  HAHB RS-485 transceiver (adapter board), R/T CN1 bidirectional,
  Wi-Fi module CN3 UART, mainboard UART CN1 grey/blue
- **Logic analyser**: Saleae

---

## Probe setup

| Channel name (CSV)              | Source file              | Capture point                                           | Bus type        |
|---------------------------------|--------------------------|---------------------------------------------------------|-----------------|
| `mainboardGrey`                 | Session 4.csv            | CN1 grey wire — mainboard RXD (display → mainboard)    | disp-mainboard  |
| `mainboardBlue`                 | Session 4.csv            | CN1 blue wire — mainboard TXD (mainboard → display)    | disp-mainboard  |
| `wifiBrown`                     | Session 4.csv            | CN3 brown wire — Wi-Fi module RX (display → Wi-Fi)     | uart            |
| `wifiOrange`                    | Session 4.csv            | CN3 orange wire — Wi-Fi module TX (Wi-Fi → display)    | uart            |
| `bidirectionalExtensionBoard`   | Session 4.csv            | CN1 R/T pin — bidirectional half-duplex                 | r-t_1           |
| `Channel 6`                     | Session 4.hahb.raw.csv   | RS-485 transceiver on adapter board — sum (all traffic) | hahb_raw_chip   |
| `Channel 7`                     | Session 4.hahb.raw.csv   | RS-485 transceiver on adapter board — MFB-X → display   | hahb_raw_chip   |

Channel 6 sees all HAHB traffic; Channel 7 sees MFB-X → display direction only.
Channel 6 minus Channel 7 = display → MFB-X direction.

Same **KJR-12x** wired wall controller and **MFB-X** adapter board as Session 3.

---

## Follow-Me configuration

- **Active throughout the session**: yes
- **Temperature reported**: 13 °C (constant)
- **Sensor source**: KJR-12x internal (display) sensor — not an external sensor

---

## Initial state (at capture start)

- **System power**: OFF (full power-off before recording started)
- **Mode**: Heat (set at power-on, unchanged throughout)
- **Setpoint**: 22 °C (initial value when unit started)
- **Fan**: Auto (initial value when unit started)

---

## Operator action sequence

Timing is approximate — exact timestamps are derivable from the capture.

| Step | Action                                    | Expected state after        |
|------|-------------------------------------------|-----------------------------|
| 1    | Recording started with system fully off   | No bus traffic              |
| 2    | System powered on                         | Power-on sequence begins    |
| 3    | (observe) Wall controller shows 13 °C env | Follow-Me active, Heat/Auto/22 °C |
| 4    | Setpoint increased: 22 °C → 23 °C        | Heat/Auto/23 °C             |
| 5    | Setpoint increased: 23 °C → 24 °C        | Heat/Auto/24 °C             |
| 6    | Fan changed: Auto → lowest               | Heat/Low/24 °C              |
| 7    | Fan changed: lowest → mid               | Heat/Mid/24 °C              |
| 8    | Fan changed: mid → highest              | Heat/High/24 °C             |
| 9    | Fan changed: highest → Auto             | Heat/Auto/24 °C             |
| 10   | Setpoint increased: 24 °C → 25 °C       | Heat/Auto/25 °C             |
| 11   | (passive observation until end of capture) | Heat/Auto/25 °C           |

---

## Key analysis opportunities in this session

- **Power-on sequence**: first capture of the full startup bus traffic across all buses simultaneously.
- **Wi-Fi UART + HAHB simultaneous**: allows direct correlation of UART 0x41 optCommand=0x01 Follow-Me temperature frames against XYE C6 Follow-Me frames on the same timeline. See Session 3 findings §7 for open questions this session may resolve.
- **Known setpoint steps**: 22 → 23 → 24 → 25 °C in Heat mode — confirms temperature encoding hypothesis (XYE: T + 0x40; R-T: T + 0x70) across four data points.
- **Fan speed sweep**: Auto → Low → Mid → High → Auto — first capture of all fan speed values; decodes the fan byte in UART 0x40, XYE C3, and R-T bus simultaneously.
- **Follow-Me at known temperature**: 13 °C held constant throughout. If 0x41 optCommand=0x01 frames appear on the Wi-Fi UART, body[5] should be `13 × 2 + 50 = 76 = 0x4C`.

---

## Open questions this session should address

- Do UART 0x41 optCmd=0x01 Follow-Me temperature frames (body[5]=0x4C for 13 °C) appear on the Wi-Fi UART bus (wifiBrown/wifiOrange)?
- Does the XYE C3 byte[8] carry 13 °C (0x4D = 13 + 0x40) during Follow-Me steady-state, or the user setpoint?
- What does the power-on sequence look like across all buses?
- What fan speed values appear in the R-T 0x40 body for Low / Mid / High?
