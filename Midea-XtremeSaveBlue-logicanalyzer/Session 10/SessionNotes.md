# Session 10 — Session Notes (Operator Playbook)

Celsius / Fahrenheit unit switch tracing. Purpose: trace how the C/F
temperature unit switch propagates across buses (UART Wi-Fi → R/T → XYE),
determine whether temperature encoding changes in F mode, and observe IR
remote C/F switching behavior.

**Observation to investigate**: Setting the app to Fahrenheit causes the wall
controller (KJR-120M) and the AC display to switch to Fahrenheit. Using the
IR remote (which is always Celsius) switches everything back.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 7–9 — all internal display board buses
- **Logic analyser**: Saleae
- **Wi-Fi dongle**: CONNECTED, paired with app (needed for F switch)
- **Wired controller**: KJR-120M (observe display changes)
- **IR remote**: Standard Midea IR remote (always Celsius at start)
- **Buses to capture**: All — UART (Wi-Fi), R/T (busadapter ↔ display), XYE (HAHB), disp-mainboard, IR

---

## Probe setup

Same channel configuration as Sessions 7–9 plus IR channel.
See [channels.yaml](channels.yaml).

---

## Follow-Me configuration

- **Active at start**: YES (keep from prior session or enable before recording)
- **Sensor**: KJR-120M internal sensor
- **Why**: Allows observing whether FM temperature encoding changes in F mode

---

## Initial state (verify before recording)

- **System power**: ON
- **Mode**: Heat (stable, consistent)
- **Setpoint**: 23 °C
- **Fan**: Auto
- **Follow Me**: ON
- **Temperature unit**: Celsius (default)
- **IR remote**: Set to Celsius

---

## Operator playbook

### Phase 1 — Baseline in Celsius (no changes, ~30 s)

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 1 | Start recording | — | All buses idle, C mode baseline | |
| 2 | Hold ~10 s, no changes | — | R/T polling cycle, 0xC0 body[10] bit 2 = 0 (Celsius) | |

### Phase 2 — Switch to Fahrenheit via app

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 3 | Set temperature unit to Fahrenheit | App | UART 0x40 SET: body[10] bit 2 should change to 1 | ok |
| 4 | Observe KJR-120M display | Visual | Does it switch to °F? How fast? | ~5 sec |
| 5 | Observe AC display (if visible) | Visual | Does it switch to °F? | direct |
| 6 | Hold ~10 s | — | R/T 0xC0 body[10] bit 2 readback, XYE C0 response fields | |
| 7 | Note: what does the KJR-120M show as setpoint? | Visual | 23 °C = 73 °F — does it show 73? | shows 73 |

### Phase 3 — Temperature changes in Fahrenheit mode

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 8 | Increase setpoint +1 step via app | App | What value does the UART 0x40 body[2] carry? °F or °C? | set 74 |
| 9 | Increase setpoint +1 step via app | App | Second data point for encoding | set 75 |
| 10 | Decrease setpoint -1 step via KJR-120M | Wired ctrl | Does KJR-120M step in °F increments? What does R/T 0x40 body[2] carry? | 74? |
| 11 | Decrease setpoint -1 step via KJR-120M | Wired ctrl | Second data point | 73? |
| 12 | Hold ~5 s | — | Steady-state in F mode | |

### Phase 4 — Switch back to Celsius via IR remote

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 13 | Press any temperature button on IR remote | IR remote | IR remote is always Celsius — does this force unit back to C? | 5 seconds app. send 24 c |
| 14 | Observe KJR-120M display | Visual | Does it switch back to °C? | 5 seconds wall? |
| 15 | Hold ~5 s | — | All buses should show body[10] bit 2 = 0 again | |

### Phase 5 — Switch to Fahrenheit again, then back via app

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 16 | Set temperature unit to Fahrenheit | App | Second F switch — confirm reproducibility | set app f |
| 17 | Hold ~5 s | — | Steady-state F mode | |
| 18 | Set temperature unit back to Celsius | App | App-initiated C switch (vs IR-initiated in Phase 4) | set app c |
| 19 | Hold ~5 s | — | Confirm all buses return to C mode | set 23 c, all c |

### Phase 6 — Follow Me disable in Fahrenheit mode

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 20 | Set temperature unit to Fahrenheit | App | Third F switch | set f, now 73 f displaying |
| 21 | Hold ~5 s | — | FM active in F mode — check R/T 0x41 body[5] encoding | room controller shows 76 f local temp. switched off, then on, and off again the followme |
| 22 | Disable Follow Me | KJR-120M | Does R/T 0x40 body[8] bit 7 clear? Does T1 switch to own thermistor? | |
| 23 | Hold ~5 s | — | Post-FM-disable in F mode | |
| 24 | Set temperature unit back to Celsius | App | Return to C mode, FM still off | |
| 25 | Hold ~5 s | — | Steady-state: FM off, Celsius | |

### Phase 7 — KJR-120M C/F switch (if available)

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 26 | Check KJR-120M menu for C/F setting | KJR-120M | Does the menu have a temperature unit option? | no, use the remote control via IR on the IR rec. of the display, set to 78 f |
| 27a | **If yes**: switch KJR-120M to Fahrenheit | KJR-120M | Does R/T 0x40 body[10] bit 2 change? Does AC display follow? | |
| 27b | **If no**: skip to Phase 8 | — | Note: KJR-120M has no C/F setting | |
| 28 | Hold ~5 s | — | Observe propagation to all buses | app turns to f, local display too! |
| 29 | Switch KJR-120M back to Celsius (if changed) | KJR-120M | Restore state | via rc, change temp to 77 f and then back to c, sending 24 deg c this time |

### Phase 8 — IR remote Fahrenheit switch (FM off)

| Step | Action | Control | What to observe | Actual result |
|------|--------|---------|-----------------|---------------|
| 30 | Switch IR remote to Fahrenheit | IR remote | Change remote's own unit setting to °F | remote changed, sending 79 f |
| 31 | Press temperature up on IR remote | IR remote | Does the unit switch to F? What IR frame is sent? | |
| 32 | Hold ~5 s | — | Check all buses — does body[10] bit 2 change to 1? | |
| 33 | Press temperature down on IR remote | IR remote | Second data point in F mode via IR | 78 pressed, propagated then 77 |
| 34 | Hold ~5 s | — | Observe KJR-120M display — does it show °F? | yes 77 |
| 35 | Switch IR remote back to Celsius | IR remote | Restore remote to °C | |
| 36 | Press temperature up on IR remote | IR remote | Forces unit back to C | sending 24 deg c, another press to 25 c |
| 37 | Hold ~5 s | — | Confirm all buses back to C | |
| 38 | Stop recording | — | End of session | at session end the app reports approx 4.2 deg outside, 24.5 inside |

---

## Key protocol fields checked in analysis

| Field | Location | C mode | F mode |
|-------|----------|--------|--------|
| Temperature unit flag | 0x40 SET body[10] bit 2 | 0 | 1 |
| Temperature unit readback | 0xC0 RSP body[10] bit 2 | 0 | 1 |
| Setpoint encoding | 0x40 SET body[2] bits[3:0] | T − 16 (Celsius) | T − 16 (Celsius, unchanged) |
| FM temperature encoding | 0x41 body[5] | T × 2 + 50 (Celsius) | T × 2 + 50 (Celsius, unchanged) |
| XYE C0/C3 setpoint | byte[10] / byte[8] | bit7=0, T + 0x40 | bit7=1, T_F + 0x87 |
| XYE D0 setpoint | byte[7] | bit7=0, T + 0x40 | bit7=1, T_F + 0x87 |
| IR D5 follow-up unit flag | byte[3] bit 0 | 0 | 1 |

---

## Session environment

- **Date**: 2026 (exact date not recorded)
- **Outdoor temp at session end**: ~4.2 °C (app report)
- **Indoor temp at session end**: ~24.5 °C (app report)
- **Session duration**: ~705 s (~11.7 min)
- **Total frames captured**: 15,988 (incl. 18 IR frames)

---

## Analysis

See [findings.md](findings.md) for the full analysis results.
