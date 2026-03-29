# Session 7 — Session Notes (Operator Playbook)

Mode sweep with single-step transitions. Purpose: decode mode byte values,
confirm SET_TEMP at boundary setpoints, identify T2B behavior in Cool mode,
and observe C4/C6 byte[20] across operating modes.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 4–6 — all internal display board buses
- **Logic analyser**: Saleae
- **Wi-Fi stick**: REMOVED (no Wi-Fi module connected during this session)
- **Wi-Fi on remote**: DISABLED

---

## Probe setup

Same channel configuration as Session 4/6. See [Session 4 channels.yaml](../Session%204/channels.yaml).
Omit wifiBrown / wifiOrange channels (Wi-Fi stick removed).

---

## Follow-Me configuration

- **Active**: yes (KJR-12x connected, internal sensor)
- **Sensor location**: same as Sessions 4–6

---

## Operator playbook

**Rules:**
- Only ONE change per step (temperature OR mode, never both)
- Temperature changes are always +1 °C or -1 °C (never jump)
- Hold each step for ~30 seconds before proceeding to the next
- Note the approximate time of each button press (or mark with a mental count)

### Phase 1 — Heat mode, sweep setpoint down to minimum

Start from the current state (expected: Heat / Auto / 23 °C from Session 6).

| Step | Action | Expected state after | What this confirms |
|------|--------|---------------------|--------------------|
| 1 | Start recording, no changes | Heat / Auto / 23 °C | Baseline, steady state |
| 2 | Setpoint 23 → 22 °C | Heat / Auto / 22 °C | |
| 3 | Setpoint 22 → 21 °C | Heat / Auto / 21 °C | |
| 4 | Setpoint 21 → 20 °C | Heat / Auto / 20 °C | |
| 5 | Setpoint 20 → 19 °C | Heat / Auto / 19 °C | |
| 6 | Setpoint 19 → 18 °C | Heat / Auto / 18 °C | |
| 7 | Setpoint 18 → 17 °C | Heat / Auto / 17 °C | |
| 7a | Setpoint 17 → 16 °C | Heat / Auto / 16 °C | Minimum setpoint confirmed = 16 °C |

> Minimum setpoint: **16 °C** (confirmed by operator).
> Expected XYE byte[10]: 0x57 → 0x56 → 0x55 → 0x54 → 0x53 → 0x52 → 0x51 → 0x50

### Phase 2 — Heat mode, sweep setpoint up to maximum

| Step | Action | Expected state after | What this confirms |
|------|--------|---------------------|--------------------|
| 8 | Setpoint min → min+1 °C | Heat / Auto / 18 °C | Reversal |
| 9 | Setpoint +1 °C | Heat / Auto / 19 °C | |
| 10 | Setpoint +1 °C | Heat / Auto / 20 °C | |
| 11 | Setpoint +1 °C | Heat / Auto / 21 °C | |
| 12 | Setpoint +1 °C | Heat / Auto / 22 °C | |
| 13 | Setpoint +1 °C | Heat / Auto / 23 °C | |
| 14 | Setpoint +1 °C | Heat / Auto / 24 °C | |
| 15 | Setpoint +1 °C | Heat / Auto / 25 °C | |
| 16 | Setpoint +1 °C | Heat / Auto / 26 °C | |
| 17 | Setpoint +1 °C | Heat / Auto / 27 °C | |
| 18 | Setpoint +1 °C | Heat / Auto / 28 °C | |
| 19 | Setpoint +1 °C | Heat / Auto / 29 °C | |
| 20 | Setpoint +1 °C | Heat / Auto / 30 °C | Maximum setpoint confirmed = 30 °C |

> Maximum setpoint: **30 °C** (confirmed by operator).
> Expected XYE byte[10] at 30 °C: 0x5E (= 30 + 0x40)

### Phase 3 — Mode transition: Heat → Cool

Return to a neutral setpoint first, then switch mode.

| Step | Action | Expected state after | What this confirms |
|------|--------|---------------------|--------------------|
| 21 | Setpoint 30 → 29 °C | Heat / Auto / 29 °C | |
| 22 | Setpoint 29 → 28 °C | Heat / Auto / 28 °C | |
| 23 | Setpoint 28 → 27 °C | Heat / Auto / 27 °C | |
| 24 | Setpoint 27 → 26 °C | Heat / Auto / 26 °C | |
| 25 | Setpoint 26 → 25 °C | Heat / Auto / 25 °C | Mid-range neutral |

> **Service menu at step 25** (compressor had stopped — heat reached):
> Room = 24 °C, T2 = 38 °C, T3 = 15 °C, T4 = 4 °C, Tp = 47 °C.
> Tp dropped from 74 °C (Session 6) to 47 °C because compressor was off and cooling down.
> T3 rose from 2 °C to 15 °C (outdoor coil warming toward ambient with compressor off).

| 26 | **Mode: Heat → Cool** | Cool / Auto / 25 °C | Mode byte changes |

> KJR-12x has no direct Heat→Cool button — must cycle through modes.
> Intermediate modes may have been hit briefly. Exact cycle order unknown —
> decode from capture (look for rapid C3 Set sequence with changing mode byte).

> Hold 30 s after mode change — observe whether T2B (byte[13]) changes from 0x00,
> whether C4/C6 byte[20] changes, and whether the compressor behavior shifts.

### Phase 4 — Cool mode, sweep setpoint down to minimum

| Step | Action | Expected state after | What this confirms |
|------|--------|---------------------|--------------------|
| 27 | Setpoint 25 → 24 °C | Cool / Auto / 24 °C | |
| 28 | Setpoint 24 → 23 °C | Cool / Auto / 23 °C | |
| 29 | Setpoint 23 → 22 °C | Cool / Auto / 22 °C | |
| 30 | Setpoint 22 → 21 °C | Cool / Auto / 21 °C | |
| 31 | Setpoint 21 → 20 °C | Cool / Auto / 20 °C | |
| 32 | Setpoint 20 → 19 °C | Cool / Auto / 19 °C | |
| 33 | Setpoint 19 → 18 °C | Cool / Auto / 18 °C | |
| 34 | Setpoint 18 → 17 °C | Cool / Auto / 17 °C | |
| 34a | Setpoint 17 → 16 °C | Cool / Auto / 16 °C | Minimum = 16 °C, fan got loud |

> Minimum cool setpoint: **16 °C** (confirmed). Fan speed increased audibly at low setpoint.
> Expected XYE byte[10] at 16 °C: 0x50

### Phase 5 — Cool mode, sweep setpoint up to maximum

| Step | Action | Expected state after | What this confirms |
|------|--------|---------------------|--------------------|
| 35 | Setpoint 17 → 18 °C | Cool / Auto / 18 °C | |
| 36 | Setpoint +1 °C | Cool / Auto / 19 °C | |
| 37 | Setpoint +1 °C | Cool / Auto / 20 °C | |
| 38 | Setpoint +1 °C | Cool / Auto / 21 °C | |
| 39 | Setpoint +1 °C | Cool / Auto / 22 °C | |
| 40 | Setpoint +1 °C | Cool / Auto / 23 °C | |
| 41 | Setpoint +1 °C | Cool / Auto / 24 °C | |
| 42 | Setpoint +1 °C | Cool / Auto / 25 °C | |
| 43 | Setpoint +1 °C | Cool / Auto / 26 °C | |
| 44 | Setpoint +1 °C | Cool / Auto / 27 °C | |
| 45 | Setpoint +1 °C | Cool / Auto / 28 °C | |
| 46 | Setpoint +1 °C | Cool / Auto / 29 °C | |
| 47 | Setpoint +1 °C | Cool / Auto / 30 °C | Maximum = 30 °C (confirmed) |

> Maximum cool setpoint: **30 °C** (confirmed).
> Expected XYE byte[10] at 30 °C: 0x5E

### Phase 6 — Mode transitions: Cool → Dry → Fan → Heat

Return to neutral setpoint, then step through remaining modes.

| Step | Action | Expected state after | What this confirms |
|------|--------|---------------------|--------------------|
| 48 | Setpoint 30 → 29 °C | Cool / Auto / 29 °C | |
| 49 | Setpoint 29 → 28 °C | Cool / Auto / 28 °C | |
| 50 | Setpoint 28 → 27 °C | Cool / Auto / 27 °C | |
| 51 | Setpoint 27 → 26 °C | Cool / Auto / 26 °C | |
| 52 | Setpoint 26 → 25 °C | Cool / Auto / 25 °C | Neutral |
| 53 | **Mode: Cool → Dry** | Dry / Auto / 25 °C | Dry mode byte |
| 54 | (hold 30 s, observe) | Dry / Auto / 25 °C | D0, C0, C4 in Dry mode |
| 55+ | **Extended sequence** (deviated from playbook — see below) | | |

> **Actual Phase 6 sequence** (operator recalled from memory, order approximate):
> - Mode cycling: Dry → Heat → Fan (and possibly Auto mode)
> - Fan speed sweep: Auto → Low → Mid → Max
> - Mode to Auto (system auto-select heat/cool?)
> - Mode to Heat, fan still at Max, then fan back to Auto
> - Swing vertical: Off → On → Off
> - Swing horizontal: Off → On → Off
> - Note: swing was not physically visible because compressor was off (heat reached)
>
> Exact sequence and timing must be decoded from the capture — rapid C3 Set commands
> with changing mode/fan/swing bytes will reveal the order.

| 56 | **Disable Follow-Me** | Follow-Me off (KJR-12x menu setting) | Follow-Me disable byte? |
| 57 | Setpoint → 27 °C | Heat / Auto / 27 °C | State after Follow-Me off |
| 58 | (hold, observe) | Heat / Auto / 27 °C | Does R-T 0x41 body[4] flag clear? |
| 59 | Stop recording | — | |

### Phase 7 — Follow-Me disable and end

See steps 56–59 above (merged into Phase 6 table).

---

## Expected byte values (pre-calculated)

### XYE C0 byte[10] SET_TEMP (T + 0x40)

| °C | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 |
|----|----|----|----|----|----|----|----|----|----|----|----|----|----|----|-----|
| hex | 50 | 51 | 52 | 53 | 54 | 55 | 56 | 57 | 58 | 59 | 5A | 5B | 5C | 5D | 5E |

### XYE C0 byte[8] mode (expected, based on codeberg/ESPHome)

| Mode | Expected byte[8] | Notes |
|------|-------------------|-------|
| Heat | `0x84` | Confirmed Sessions 3–6 |
| Cool | `0x82` or `0x88`? | To be determined |
| Dry | `0x81` or `0x84`? | To be determined |
| Fan only | `0x85` or `0x80`? | To be determined |

---

## Key analysis targets

1. **Mode byte values**: C0 byte[8], D0 byte[5], C6 byte[16] for Cool / Dry / Fan-only
2. **SET_TEMP at extremes**: Does T+0x40 hold at min (16/17 °C) and max (30 °C)?
3. **T2B (C0 byte[13])**: Does it change from `0x00` in Cool mode?
4. **C4/C6 byte[20] (0xD6 = 87 °C in Heat)**: What happens in Fan-only when compressor stops?
5. **C4/C6 byte[19] Tp**: Does it drop in Fan-only mode? (compressor off → Tp cools down)
6. **Wi-Fi removal effect**: Any change in R-T polling pattern or frame types?
7. **Follow-Me path**: Does R-T 0x41 body[5] still carry room temperature without Wi-Fi?
8. **C6 Follow-Me pairs**: One per setpoint step → expect ~40+ C6 pairs in this session
