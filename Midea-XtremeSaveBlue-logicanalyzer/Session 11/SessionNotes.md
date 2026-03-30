# Session 11 — Session Notes

Multi-feature test session without formal playbook. Turbo, LED, sleep, fan speed
percentages, frost protection, power on/off, and MFB-X window contact testing.
All in Celsius mode. Session starts with IR service menu readout providing
ground truth sensor values.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 7-10 — all internal display board buses + IR
- **Logic analyser**: Saleae
- **Wi-Fi dongle**: CONNECTED, paired with app
- **Wired controller**: KJR-120M
- **IR remote**: Standard Midea IR remote (Celsius mode)

---

## Probe setup

Same channel configuration as Session 10 including IR.
See [channels.yaml](channels.yaml).

---

## Initial state

- **System power**: ON
- **Mode**: Heat
- **Setpoint**: 25 C
- **Fan**: Auto
- **Follow Me**: OFF
- **Temperature unit**: Celsius

---

## Operator action log

Reconstructed from [Session 11 Quicknotes.md](Session%2011%20Quicknotes.md) with
timestamps from protocol analysis.

### Phase 1 — Service menu readout (t=2-71 s)

IR remote B9 frames step through service menu pages:

| Time (s) | IR param | Display shows | Protocol value |
|----------|----------|---------------|----------------|
| 2.2      | 0x01     | T1 = 24 C    | R/T Grp1: 24.0 C |
| 14.8     | 0x02     | T2 = 29 C    | R/T Grp1: 29.5 C (drifting) |
| 22.9     | 0x03     | T3 = 3 C     | R/T Grp1: 3.5 C |
| 30.6     | 0x04     | T4 = 3 C     | R/T Grp1: 3.5 C |
| 38.6     | 0x05     | Tp = 28 C    | R/T Grp1: 28 C |
| 50.9     | 0x06     | FT = 27      | R/T Grp1: 27 Hz |
| 59.7     | 0x07     | FR = 26      | R/T Grp1: 26 Hz |
| 71.2     | 0xFF     | (exit menu)  | — |

### Phase 2 — Turbo + temperature sweep (t=103-200 s)

| Time (s) | Action | Source | UART observation |
|----------|--------|--------|------------------|
| ~103     | Enable Turbo mode | App | body[8] bit 5=1, FT jumps to 90 Hz |
| 103      | Set temp 25 C | App | Temp=25, Turbo=yes |
| 115      | Set temp 26 C | App | Temp=26, body[10] Turbo reverts to no |
| 116      | Set temp 27 C | App | |
| 117      | Set temp 28 C | App | |
| 169      | Disable display LED | App | Beep flag unclear |
| 169      | Set temp 29 C | App | "unit does not beep when setting 29deg now!" |
| 201      | Enable display LED, set temp 28 C | App | |

### Phase 3 — Turbo toggle via wall controller (t=200-361 s)

| Time (s) | Action | Source | UART observation |
|----------|--------|--------|------------------|
| ~200     | Disable Turbo | Wall ctrl | (R/T only, not on UART) |
| 330      | Set temp 29 C, Turbo off confirmed | App | body[8] Turbo=no |
| 336      | Set temp 28 C | App | |
| ~340     | Enable Turbo via wall ctrl | Wall ctrl | (R/T only) |
| ~350     | Disable Turbo in app | App | |
| 361      | Set temp 25 C, LED off? | App | Beep: no |

### Phase 4 — Sleep mode (t=361-429 s)

| Time (s) | Action | Source |
|----------|--------|--------|
| ~361     | Click "Smart Sleep" in app | App |
| ~400     | Exit sleep function | App |
| ~410     | LED went out again? | — |
| 429      | Enable something, set temp 24 C | App |

### Phase 5 — Frost protection (t=429-537 s)

| Time (s) | Action | Source | UART observation |
|----------|--------|--------|------------------|
| 464      | Enable frost protection | App | body[21] bit 7 = 1 |
| ~470     | Note: room controller does not recognize FP | Visual | |
| ~480     | Used wall ctrl to exit FP | Wall ctrl | (R/T only) |
| ~510     | Enable FP again via app | App | body[21] bit 7 = 1 |
| 537      | Disable FP via app | App | body[21] bit 7 = 0 |

### Phase 6 — Fan speed percentage testing (t=537-651 s)

| Time (s) | Action | Source | body[3] bits[6:0] | Wall ctrl display |
|----------|--------|--------|-------------------|-------------------|
| 559      | Set fan to 21% | App | 21 | Low fan |
| 595      | Set fan to 8% | App | 8 | — |
| 606      | Set fan to 1% | App | 1 | — |
| 622      | Set fan to 96% | App | 96 | — |
| 634      | Set fan to 100% | App | 100 | — |
| 641      | Set fan to Auto | App | 102 | — |

### Phase 7 — Power on/off (t=651-714 s)

| Time (s) | Action | Source | UART body[1] bit 0 |
|----------|--------|--------|-------------------|
| 651      | Turn off unit | App | 0 (OFF) |
| ~660     | Turn on unit | Wall ctrl | (R/T only, no UART) |
| ~680     | Turn off unit | Wall ctrl | (R/T only) |
| 697      | Turn on unit | App | 1 (ON) |
| 715      | Set temp 25 C | App | |

### Phase 8 — Window contact / MFB-X (t=836-895 s)

| Time (s) | Action | Source | Observation |
|----------|--------|--------|-------------|
| ~836     | Remove window contact on MFB-X | Manual | HVAC display shows "CP", room controller shows "CP" |
| ~850     | Close contact | Manual | Return to normal operation |
| ~860     | Open contact again | Manual | App says "just off" |
| ~870     | Send ON via app | App | Nothing happens, just beep on HVAC |
| 895      | Close contact, set 24 C | App | App: outside 4.1 C, inside 26 C |

Note: CP error not visible in R/T 0xC0 error code field — carried elsewhere.
The window contact is a dry contact on the MFB-X HAHB adapter board.

---

## Session environment

- **Outdoor temp at session end**: ~4.1 C (app report)
- **Indoor temp at session end**: ~26 C (app report)
- **Session duration**: ~923 s (~15.4 min)
- **Total frames captured**: 20,937 (incl. 16 IR frames)

---

## Analysis

See [findings.md](findings.md) for the full analysis results.
