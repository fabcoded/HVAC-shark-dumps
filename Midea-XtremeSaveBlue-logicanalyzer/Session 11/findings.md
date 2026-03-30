# Session 11 — Findings

## Session context

Multi-feature test session without formal playbook. Operator cycled through Turbo,
LED control, sleep, fan speed percentages, frost protection, power on/off, and
MFB-X window contact. All in Celsius mode — no C/F switching.

Key value: the session starts with an IR service menu readout (B9 frames), providing
ground truth sensor values that can be time-aligned with protocol readings.

For operator notes, see [SessionNotes.md](SessionNotes.md).
For original quicknotes, see [Session 11 Quicknotes.md](Session%2011%20Quicknotes.md).

---

## Buses captured

| Channel               | Direction             | Frames  | Polling cycle |
|-----------------------|-----------------------|---------|---------------|
| UART (Wi-Fi CN3)      | Bidirectional         | 665     | ~8 s          |
| R/T (CN1 ext board)   | Bidirectional         | 1,713   | ~5.5 s        |
| XYE (HAHB RS-485)     | Both (CH6-CH7)        | 4,696   | ~0.6 s        |
| disp-mainboard (CN1)  | Grey + Blue           | 13,847  | ~60 ms        |
| IR                    | toACdisplay           | 16      | (event-driven) |

Total: 20,937 frames over 922.8 s (~15.4 min).

---

## 1. B9 IR service menu parameter-to-sensor mapping — **Confirmed**

Session 11 captured 8 B9 IR frames (parameters 0x01-0x07 + 0xFF exit) while the
operator stepped through the service menu, noting the displayed value on each page.
Time-aligned cross-referencing against R/T 0xC1 Group 1 protocol readings confirms
the parameter index selects which sensor the display shows.

| IR time (s) | byte[4] | Operator read | Sensor | R/T Grp1 at same time | Match |
|-------------|---------|---------------|--------|----------------------|-------|
| 2.2         | 0x01    | T1 = 24       | T1 indoor coil | 24.0 C (body[10], (78-30)/2) | **exact** |
| 14.8        | 0x02    | T2 = 29       | T2 heat exchanger | 29.5 C (body[11], (89-30)/2, drifting) | **+/-0.5** (drift) |
| 22.9        | 0x03    | T3 = 3        | T3 outdoor coil | 3.5 C (body[12], (57-50)/2) | **display rounds** |
| 30.6        | 0x04    | T4 = 3        | T4 outdoor ambient | 3.5 C (body[13], (57-50)/2) | **display rounds** |
| 38.6        | 0x05    | Tp = 28       | Tp discharge | 28 C (body[14], raw) | **exact** |
| 50.9        | 0x06    | FT = 27       | FT target freq (indoor target freq) | 27 Hz (body[5], raw) | **exact** |
| 59.7        | 0x07    | FR = 26       | FR running freq (compressor freq) | 26 Hz (body[4], raw) | **exact** |
| 71.2        | 0xFF    | (exit menu)   | — | — | — |

T1, Tp, FT, FR match exactly. T2 has +/-0.5 C (thermal drift during the 13 s between
T1 and T2 reads). T3/T4 show 3.5 C in protocol but 3 on display (integer rounding).

This also confirms:
- R/T 0xC1 Group 1 body[4] = **FR — compressor running frequency** (compressor freq)
  in Hz — previously labeled "Compressor freq" with Hypothesis confidence
- R/T 0xC1 Group 1 body[5] = **FT — compressor target frequency** (indoor target freq)
  in Hz — previously labeled "Indoor target freq" with Hypothesis confidence

### Turbo effect on FR/FT

When Turbo is enabled (t=103 s), FT jumps immediately to 90 Hz. FR ramps to follow:

| Time (s) | FT (target) | FR (running) | Event |
|----------|-------------|-------------|-------|
| 4.0      | 24 Hz       | 24 Hz       | Baseline (service menu) |
| 103.0    | 27 Hz       | 26 Hz       | Turbo just enabled (matches menu FT=27, FR=26) |
| 119.4    | 90 Hz       | 39 Hz       | FT jumped to 90, FR ramping |
| 168.9    | 90 Hz       | 56 Hz       | FR still ramping |
| 201.9    | 90 Hz       | 64 Hz       | |
| 328.1    | 90 Hz       | 80 Hz       | FR approaching target |

---

## 2. Temperature sensor formula cross-validation — **Confirmed S11**

The IR service menu provides hardware ground truth. Cross-checking against all
three bus types (R/T 0xC0, R/T 0xC1 Group 1, XYE C0/C4/C6):

### R/T 0xC0 (body[11], body[12])

| Sensor | body offset | Raw at t=1.8 s | Formula | Decoded | Decimal (body[15]) | Precise | Menu |
|--------|------------|-----------------|---------|---------|-------------------|---------|------|
| Indoor T1 | body[11] | 98 (0x62) | (98-50)/2 | 24.0 C | +0.2 | **24.2 C** | 24 |
| Outdoor T4 | body[12] | 57 (0x39) | (57-50)/2 | 3.5 C | +0.8 | **3.8 C** | 3 |

### R/T 0xC1 Group 1 (body[10]-body[14])

All formulas match the service menu within display rounding. See table in finding 1.

### XYE C0 (byte[11]-byte[14]) and C4/C6 (byte[21]-byte[22])

| Sensor | Frame type | Byte | Raw at t=0.4 s | Formula | Decoded | Menu |
|--------|-----------|------|-----------------|---------|---------|------|
| T1 indoor air | C0 | byte[11] | 0x58 | (0x58-40)/2 | 24.0 C | 24 |
| T2A indoor coil in | C0 | byte[12] | 0x65 | (0x65-40)/2 | 30.5 C | 29 (drift) |
| **T2B indoor coil out** | C0 | byte[13] | **0x00** | (0x00-40)/2 | **-20.0 C** | **inactive** |
| T3 outdoor coil | C0 | byte[14] | 0x2F | (0x2F-40)/2 | 3.5 C | 3 |
| T4 outdoor ambient | C4/C6 | byte[21] | 0x2F | (0x2F-40)/2 | 3.5 C | 3 |
| Tp discharge | C4/C6 | byte[22] | 0x66 | (0x66-40)/2 | 31.0 C | 28 (drift) |

**T2B = 0x00 across entire session** — the XtremeSaveBlue has a single indoor coil
probe (T2A). T2B (byte[13]) is unused on this hardware. The decoded -20.0 C is a
sentinel value, not a physical reading.

---

## 3. Turbo flag: body[8] bit 5 vs body[10] bit 1 — **Consistent**

Turbo is enabled via the app at t=103 s and disabled at t=330 s.

| UART field | t=103 (ON) | t=115 (temp change) | t=330 (OFF) |
|------------|-----------|--------------------|----|
| body[8] bit 5 (FollowMe line) | **yes** | **yes** | **no** |
| body[10] bit 1 (Sleep/Turbo line) | **yes** | **no** | **no** |
| 0xC0 RSP body[10] bit 1 | no | no | no |

body[10] bit 1 shows Turbo=yes **only in the first SET command** after enabling.
Subsequent SET commands (with temperature changes) show Turbo=no in body[10] even
though body[8] bit 5 still shows Turbo=yes. The 0xC0 response never shows
body[10] bit 1 = Turbo on.

**Interpretation**: body[8] bit 5 is the authoritative Turbo flag (persistent while
Turbo is active). body[10] bit 1 appears to be a **one-shot trigger** that is set
only on the initial enable command, not maintained. The 0xC0 response does not
reflect body[10] bit 1 as Turbo — it may have a different meaning in the response.

---

## 4. Fan speed: app sends raw percentage — **Confirmed S11**

The app sends fan speed as a raw percentage value in body[3] bits[6:0], not the
fixed levels (20/40/60/80/102) previously documented:

| Time (s) | body[3] raw | bits[6:0] | Quicknotes | Room controller display |
|----------|------------|-----------|------------|------------------------|
| 103.1    | 230 (0xE6) | 102       | (Turbo, auto) | — |
| 558.9    | 149 (0x95) | 21        | "set fan to 21%" | Low fan |
| 594.6    | 136 (0x88) | 8         | "set fan to 8%" | — |
| 606.1    | 129 (0x81) | 1         | "set fan to 1%" | — |
| 622.3    | 224 (0xE0) | 96        | "set fan to 96%" | — |
| 633.7    | 228 (0xE4) | 100       | "set fan to 100%" | — |
| 640.9    | — | 102 (auto) | "set fan to auto" | — |

body[3] bit 7 is the timer set flag (0xE6 has bit 7 set = 0x80, so 0xE6 & 0x7F = 0x66 = 102).

The room controller maps percentage values to its own level labels (21% = "Low fan").
The protocol carries the exact percentage from the app.

---

## 5. Frost protection: body[21] bit 7 — **Confirmed S11**

| Time (s) | body[21] bit 7 | Quicknotes |
|----------|---------------|------------|
| 103-429  | 0 (no)        | Normal operation |
| 463.9    | **1 (yes)**   | "click on frost protection mode. app shows fp now, display too" |
| 518.6    | 1 (yes)       | Frost protection still active |
| 536.9    | **0 (no)**    | "disable fp in app again" |

Frost protection is a single bit in body[21]. The room controller (KJR-120M) "does
not know fp" (quicknotes) — it cannot display or control this feature, but the unit
still responds to the app command.

---

## 6. Power on/off — **Confirmed S11**

| Time (s) | body[1] bit 0 | Source | Quicknotes |
|----------|--------------|--------|------------|
| 103-640  | 1 (ON)       | — | Normal operation |
| 650.8    | **0 (OFF)**  | App | "turn off unit in app" |
| 696.6    | **1 (ON)**   | App | "turn unit on in app" (note: quicknotes say on with wall controller, then off with wall controller, then on in app — only the app-initiated commands appear on UART) |

Wall-controller-initiated power changes do NOT appear on the UART bus (no UART
command generated). They are visible only on the R/T bus.

---

## 7. Window contact / CP error — **Disputed (not in 0xC0 error code)**

Quicknotes: "remove window contact on mfb-x, display shows cp" — the CP error
was confirmed visible on both the HVAC unit display AND the KJR-120M room
controller display. The window contact is a dry contact on the MFB-X HAHB
adapter board. When the contact opens, the unit enters a protection state.

However, **R/T 0xC0 body[16] (Error Code) remains "none" throughout the entire
session** — the CP error is not carried in the standard error code field. The error
may be signaled via:
- The 0x93 extension board status frame (R/T bus)
- A separate error/notification frame on the XYE/HAHB bus
- The disp-mainboard internal bus

Further investigation needed — the CP error was confirmed visible on both displays
but its protocol-level encoding location is unknown.

---

## 8. XYE setpoint confirms Celsius-only encoding — **Confirmed S11**

All 13 XYE C0 byte[10] transitions and 13 D0 byte[7] transitions have bit 7 = 0
(Celsius encoding). Decoded values: 0x57=23 C, 0x58=24 C, 0x59=25 C, 0x5B=27 C,
0x5C=28 C, 0x5D=29 C. Matches quicknotes temperature adjustments.

Confirms the Session 10 dual-encoding dissector works correctly in Celsius-only sessions.

---

## Summary of confidence upgrades from Session 11

| Field | Previous | New | Evidence |
|-------|----------|-----|----------|
| R/T Grp1 body[4] "Compressor freq" | Hypothesis | **Confirmed S11** — FR running freq (compressor freq), matches service menu FR=26 exactly at t=103 s |
| R/T Grp1 body[5] "Indoor target freq" | Hypothesis | **Confirmed S11** — FT target freq (indoor target freq), matches service menu FT=27 exactly at t=103 s |
| R/T Grp1 T1 (raw-30)/2 | Confirmed S6 | **Confirmed S6+S11** (T1=24 C matches menu) |
| R/T Grp1 T2 (raw-30)/2 | Hypothesis | **Consistent S11** (29.5 C vs menu 29, drift) |
| R/T Grp1 T3/T4 (raw-50)/2 | Confirmed S6 | **Confirmed S6+S11** |
| R/T Grp1 Tp raw C | Confirmed S6 | **Confirmed S6+S11** (28 C matches menu at Tp page time) |
| XYE C0 T2A (raw-40)/2 | Hypothesis | **Consistent S11** |
| XYE C4/C6 T4 (raw-40)/2 | Hypothesis | **Confirmed S11** |
| Frost protection body[21] bit 7 | Documented | **Confirmed S11** |
| IR B9 parameter semantics | Unknown | **Confirmed S11** (0x01-0x07 mapped to T1-FR) |
