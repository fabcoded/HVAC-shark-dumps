# Session 12 — Findings

## Session context

Cool mode testing session with mode switching, ECO, turbo, fan gear (percentage),
vane positions, anti-direct wind, night mode, and Follow Me. All Celsius, no C/F
switching. Includes IR remote usage for temperature and swing control.

For operator notes, see [SessionNotes.md](SessionNotes.md).
For original quicknotes, see [Session 12 Quicknotes.md](Session%2012%20Quicknotes.md).

---

## Buses captured

| Channel               | Direction             | Frames  |
|-----------------------|-----------------------|---------|
| UART (Wi-Fi CN3)      | Bidirectional         | 582     |
| R/T (CN1 ext board)   | Bidirectional         | 1,220   |
| XYE (HAHB RS-485)     | Both (CH6-CH7)        | 3,372   |
| disp-mainboard (CN1)  | Grey + Blue           | 9,946   |
| IR                    | toACdisplay           | 18      |

Total: 15,138 frames over 663.0 s (~11.1 min).

---

## 1. IR B2 byte[4] bits[3:0] is NOT a fixed marker — **Disputed**

protocol_ir.md documented byte[4] bits[3:0] as "always 0xC" (fixed protocol marker).
Session 12 disproves this: **all 6 B2 frames have bits[3:0] = 0x0**.

| Session | Mode | bits[3:0] values |
|---------|------|-----------------|
| 2       | Heat | 0xC in all frames |
| 10      | Heat | 0xC in all frames |
| 12      | Cool | **0x0 in all frames** |

The lower nibble may encode mode or another operational parameter, not a fixed
marker. With only two distinct values (0xC in Heat, 0x0 in Cool), the encoding
is unclear. Dry/Fan/Auto mode captures are needed to resolve.

### IR temperature encoding — extended range confirmed

Session 12 adds new data points to the bits[7:5]+20 formula:

| byte[4] | bits[7:5] | Decoded | Quicknote | Match |
|---------|-----------|---------|-----------|-------|
| 0x20    | 1         | 21 C    | "21 grad via fernbedienung" | yes |
| 0x50    | 2         | 22 C    | "use ir to set 22deg c" | yes |
| 0x60    | 3         | 23 C    | (auto swing press) | plausible |
| 0x70    | 3         | 23 C    | (subsequent press) | plausible |

Combined with Sessions 2 and 10, the confirmed range is now 21-26 C (bits 1-6).
Still missing: 20 C (bits=0) and 27 C (bits=7).

### IR byte[4] bit 4 — toggles between consecutive presses

| t (s) | byte[4] | bits[7:5] | bit 4 | Context |
|-------|---------|-----------|-------|---------|
| 331   | 0x50    | 2 (22 C)  | 1     | First IR press (22 C) |
| 332   | 0x70    | 3 (23 C)  | 1     | Second IR press (auto swing) |
| 407   | 0x60    | 3 (23 C)  | 0     | Anti-direct wind |
| 449   | 0x20    | 1 (21 C)  | 0     | 21 C via remote |
| 451   | 0x30    | 1 (21 C)  | 1     | Remote press (bit4 toggled) |
| 457   | 0x20    | 1 (21 C)  | 0     | Remote press (bit4 toggled back) |

bit 4 alternates between consecutive presses at the same temperature. This
pattern is consistent across Sessions 2, 10, and 12 — it is NOT a swing state
bit (the swing command at t=332 shows bits[7:5]=3 not 2, so the temperature
changed). bit 4 may be a **toggle/parity bit** that lets the display board
distinguish repeated identical commands from a held button.

### All D5 follow-up frames: Celsius

All 6 D5 frames show `D5660000003B` (byte[3]=0x00 = Celsius). Confirms the
Session 10 C/F flag interpretation — this session has no F switching.

---

## 2. ECO mode: body[9] bit 4 in 0xC0 response — **Confirmed S12**

| Time (s) | ECO in 0xC0 RSP | Quicknote |
|----------|-----------------|-----------|
| 6        | no              | Baseline (Heat mode) |
| 54       | **yes**         | "set mode eco" |
| 84       | **no**          | "set mode turbo, stops eco" |
| 205-end  | no              | ECO not re-enabled |

ECO at body[9] bit 4 in the 0xC0 response confirmed. Enabling Turbo disables
ECO (consistent with protocol_serial.md).

Quicknote also says "setting temp disables eco!" — confirmed: the ECO flag
disappears from 0xC0 responses after a temperature change is sent.

---

## 3. Night mode (CosySleep) via room controller — **Confirmed S12**

At t=584, the 0xC0 response shows CosySleepSw=yes and Sleep=yes (body[10] bit 0).
This corresponds to "nachtmodus am raumcontroller an" (night mode on room controller).

The night mode is initiated from the wall controller, not the app. It appears on
UART only because the app queries the status.

---

## 4. Follow Me temperature — **Confirmed S12**

One R/T 0x41 Follow Me frame at t=628: body[5]=0x62 (24.0 C). Matches quicknote
"follow me sagt 24degc (am controller aktiviert)". FM activated via the KJR-120M
wall controller.

Formula `body[5] = T_celsius * 2 + 50` confirmed (0x62 = 98, (98-50)/2 = 24.0 C).

---

## 5. XYE setpoint confirms Celsius encoding — **Confirmed S12**

All XYE C0 byte[10] values have bit 7 = 0 (Celsius):
0x53 (19 C), 0x54 (20 C), 0x55 (21 C), 0x56 (22 C), 0x57 (23 C), 0x58 (24 C).

Mode byte[8] transitions: 0x84 (Heat) at t=0-17, then 0x88 (Cool) from t=29
onwards. Confirms the XYE mode encoding for Cool mode.

byte[21] = 0x00 throughout (no protection events).

---

## 6. Swing / vane — not visible on UART

Quicknotes describe vane position changes ("set vane position medium each",
"then uppest left", "auto swing", "direktes anblasen verhindern"). However,
the UART 0xC0 response shows "Swing: Off" throughout the entire session.

Possible explanations:
- Swing state is carried in the UART 0xB0/0xB1 property protocol (not decoded here)
- Swing is only visible on the XYE bus (C6 byte[6] and D0 byte[11])
- The swing commands were sent via IR and only reached the display board, not the UART

---

## 7. Beep / LED anomalies — noted but not decoded

Quicknotes mention recurring LED state loss ("app hat wieder das led bit verlernt",
"somwhere inbetween the led was turned off? app fault?") and beep disappearing
("the unit lost its beeping inbetween?"). These suggest the app's internal state
desynchronizes with the unit — the app sends a stale LED/beep state on subsequent
commands, overriding the current setting.

The beep flag is body[1] bit 6 in 0x40 SET. Detailed tracking of this bit across
all 76 SET commands could identify when the desync occurs.
