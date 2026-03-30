# Session 10 — Findings

## Session context

Celsius / Fahrenheit unit switch tracing across all buses (UART Wi-Fi, R/T,
XYE, disp-mainboard). 8-phase operator playbook: baseline in C, switch to F
via app, temperature changes in F mode, IR remote force-back to C, Follow Me
toggle in F mode, IR remote in F mode. All buses captured simultaneously.

For operator setup and probe details, see [playbook.tmp.md](playbook.tmp.md).

---

## Buses captured

| Channel               | Direction             | Frames  | Polling cycle |
|-----------------------|-----------------------|---------|---------------|
| UART (Wi-Fi CN3)      | Bidirectional         | 508     | ~8 s          |
| R/T (CN1 ext board)   | Bidirectional         | 1,312   | ~5.5 s        |
| XYE (HAHB RS-485)     | Both (CH6–CH7)        | 3,591   | ~0.6 s        |
| disp-mainboard (CN1)  | Grey + Blue           | 10,559  | ~60 ms        |

Total: 15,970 frames over 704.7 s. No IR bus in this capture (IR effects
observed indirectly on other buses).

---

## 1. C/F switch propagates via body[10] bit 2 on UART and R/T — **Confirmed**

The app-initiated Celsius/Fahrenheit switch is sent as a single bit in the
0x40 SET command body[10]:

- **bit 2 = 0** → Celsius (body[10] = 0x00)
- **bit 2 = 1** → Fahrenheit (body[10] = 0x04)

The same bit is echoed back in the 0xC0 Status Response body[10].

### Evidence — all 8 UART 0x40 SET commands

| Frame | Time (s) | body[10] | Unit | Setpoint | Phase |
|-------|----------|----------|------|----------|-------|
| 556   | 24.5     | 0x04     | F    | 23.0°C (73.4°F) | P2: app → F |
| 2392  | 105.1    | 0x04     | F    | 23.5°C (74.3°F) | P3: app 74°F |
| 2647  | 116.3    | 0x04     | F    | 24.0°C (75.2°F) | P3: app 75°F |
| 5207  | 228.6    | 0x04     | F    | 24.0°C (75.2°F) | P5: app → F |
| 5571  | 244.2    | 0x00     | C    | 24.0°C (75.2°F) | P5: app → C |
| 6290  | 275.4    | 0x00     | C    | 23.0°C (73.4°F) | P6: app set 23°C |
| 6608  | 289.5    | 0x04     | F    | 23.0°C (73.4°F) | P6: app → F |
| 9351  | 411.2    | 0x00     | C    | 23.0°C (73.4°F) | P8: app set 23°C |

### Evidence — all 8 R/T 0x40 SET commands (KJR-120M and IR-triggered)

| Frame | Time (s) | body[10] | Unit | Setpoint | Source |
|-------|----------|----------|------|----------|--------|
| 3047  | 134.2    | 0x04     | F    | 23.5°C (74.3°F) | KJR-120M decrease |
| 3223  | 141.4    | 0x04     | F    | 23.0°C (73.4°F) | KJR-120M decrease |
| 7932  | 347.4    | 0x04     | F    | 23.0°C (73.4°F) | KJR-120M FM off |
| 8088  | 354.2    | 0x04     | F    | 23.0°C (73.4°F) | KJR-120M FM on |
| 8381  | 367.3    | 0x04     | F    | 23.0°C (73.4°F) | KJR-120M FM off |
| 10724 | 471.6    | 0x04     | F    | 25.5°C (77.9°F) | IR 78°F |
| 11888 | 522.7    | 0x04     | F    | 25.0°C (77.0°F) | IR 77°F |
| 12314 | 541.1    | 0x00     | C    | 24.0°C (75.2°F) | IR → C, 24°C |

### Dissector gap

The `decode_uart_40_set` function (lua ~line 1286) currently decodes body[10]
as Sleep and Turbo only. Bit 2 (Unit flag) is not decoded — improvement needed.
The 0xC0 Status Response decoder correctly shows "Unit: C" / "Unit: F".

---

## 2. Temperature encoding on UART and R/T is always Celsius — **Confirmed**

All temperature fields in UART and R/T commands use Celsius-internal encoding
regardless of the displayed unit. The F flag affects display only.

### Setpoint (body[2]) encoding — unchanged in F mode

Formula: `T_celsius = bits[3:0] + 16 + (bit4 × 0.5)`, bits[7:5] = mode.

| Frame | Unit | User set | body[2] | Decoded |
|-------|------|----------|---------|---------|
| 556   | F    | 73°F (22.8°C) | 0x87 | bits[3:0]=7 → 7+16 = 23.0°C |
| 2392  | F    | 74°F (23.3°C) | 0x97 | bits[3:0]=7, bit4=1 → 23.5°C |
| 2647  | F    | 75°F (23.9°C) | 0x88 | bits[3:0]=8 → 8+16 = 24.0°C |
| 5571  | C    | 24°C          | 0x88 | same formula → 24.0°C |

The app converts Fahrenheit to the nearest 0.5°C before sending.

### Indoor / outdoor temperature — unchanged in F mode

| Field | body offset | Formula | C mode | F mode | Change? |
|-------|-------------|---------|--------|--------|---------|
| Indoor T1 | body[11] | (raw-50)/2 | raw=0x62 → 24.0°C (75.2°F) | raw=0x62 → 24.0°C | **No** |
| Outdoor T4 | body[12] | (raw-50)/2 | raw=0x39 → 3.5°C (38.3°F) | raw=0x39 → 3.5°C | **No** |
| Temp decimals | body[15] | lo=indoor, hi=outdoor tenths | 0x70 (+0.0/+0.7) | 0x70-0x80 (normal drift) | **No** |
| Temp override | body[13] | raw °C | 0x0B → 23°C | 0x0C → 24°C (tracks setpoint) | **No** |

### Follow Me temperature — unchanged in F mode

All 10 R/T 0x41 Follow Me frames across the session show the same value:

```
body[5] = 0x62 → raw = 98 → T = (98 - 50) / 2 = 24.0°C (75.2°F)
Formula: body[5] = T_celsius × 2 + 50 (unchanged in F mode)
```

### Group page temperatures (0xC1, page 0x41) — unchanged in F mode

| Sensor | Formula | Baseline | During F mode | Change? |
|--------|---------|----------|---------------|---------|
| T1 indoor coil | (raw-30)/2 | raw=78 → 24.0°C (75.2°F) | raw=78 | **No** |
| T2 heat exchanger | (raw-30)/2 | raw=95 → 32.5°C (90.5°F) | raw=95 | **No** |
| T3 outdoor coil | (raw-50)/2 | raw=51 → 0.5°C (32.9°F) | raw=51 | **No** |
| T4 outdoor ambient | (raw-50)/2 | raw=57 → 3.5°C (38.3°F) | raw=57 | **No** |
| Tp discharge | raw °C | 32°C (89.6°F) | 32-34°C (compressor drift) | **No** |

---

## 3. XYE bus carries C/F flag in setpoint byte bit 7 — **Confirmed**

The XYE bus uses a dual-encoding scheme for the setpoint byte: bit 7 indicates
the temperature unit, and the lower 7 bits encode the temperature in the
display unit with a unit-dependent offset.

### Encoding formula

```
If bit 7 = 0 (Celsius):    T_C = (byte & 0x7F) - 0x40     offset = 64
If bit 7 = 1 (Fahrenheit): T_F = (byte & 0x7F) - 0x07     offset = 7
```

This encoding applies to:
- **C0 32-byte response byte[10]** — setpoint readback
- **C3 16-byte SET command byte[8]** — setpoint command
- **C6 32-byte response byte[18]** — mirrors C0 setpoint

### Evidence — all 18 XYE C0 byte[10] transitions

| Frame | Time (s) | byte[10] | bit7 | Formula | Decoded | Playbook |
|-------|----------|----------|------|---------|---------|----------|
| 5     | 0.2      | 0x57     | 0    | (0x57&0x7F)-0x40 | 23°C (73.4°F) | P1 baseline ✓ |
| 631   | 27.8     | 0xD0     | 1    | (0xD0&0x7F)-0x07 | 73°F (22.8°C) | P2 "shows 73" ✓ |
| 2481  | 108.8    | 0xD1     | 1    | (0xD1&0x7F)-0x07 | 74°F (23.3°C) | P3 "set 74" ✓ |
| 2723  | 119.6    | 0xD2     | 1    | (0xD2&0x7F)-0x07 | 75°F (23.9°C) | P3 "set 75" ✓ |
| 3067  | 134.8    | 0xD1     | 1    | (0xD1&0x7F)-0x07 | 74°F (23.3°C) | P3 KJR -1 "74?" ✓ |
| 3246  | 142.4    | 0xD0     | 1    | (0xD0&0x7F)-0x07 | 73°F (22.8°C) | P3 KJR -1 "73?" ✓ |
| 4177  | 183.2    | 0x58     | 0    | (0x58&0x7F)-0x40 | 24°C (75.2°F) | P4 IR→C "24c" ✓ |
| 5296  | 232.4    | 0xD2     | 1    | (0xD2&0x7F)-0x07 | 75°F (23.9°C) | P5 F (24°C≈75°F) ✓ |
| 5690  | 249.2    | 0x58     | 0    | (0x58&0x7F)-0x40 | 24°C (75.2°F) | P5 app→C ✓ |
| 6322  | 276.8    | 0x57     | 0    | (0x57&0x7F)-0x40 | 23°C (73.4°F) | P6 set 23°C ✓ |
| 6723  | 294.4    | 0xD0     | 1    | (0xD0&0x7F)-0x07 | 73°F (22.8°C) | P6 app→F ✓ |
| 9383  | 412.7    | 0x57     | 0    | (0x57&0x7F)-0x40 | 23°C (73.4°F) | P8 →C ✓ |
| 10745 | 472.3    | 0xD5     | 1    | (0xD5&0x7F)-0x07 | 78°F (25.6°C) | P7 "set to 78f" ✓ |
| 11923 | 524.0    | 0xD4     | 1    | (0xD4&0x7F)-0x07 | 77°F (25.0°C) | P8 "then 77" ✓ |
| 12328 | 541.5    | 0x58     | 0    | (0x58&0x7F)-0x40 | 24°C (75.2°F) | P8 IR→C "24c" ✓ |
| 13341 | 587.1    | 0xD6     | 1    | (0xD6&0x7F)-0x07 | 79°F (26.1°C) | P8 "79f" ✓ |
| 15189 | 669.9    | 0x58     | 0    | (0x58&0x7F)-0x40 | 24°C (75.2°F) | P8 →C ✓ |
| 15309 | 675.3    | 0x59     | 0    | (0x59&0x7F)-0x40 | 25°C (77.0°F) | P8 "25c" ✓ |

All 18 transitions match the playbook operator annotations.

### XYE C3 SET byte[8] — same encoding

| Frame | Time (s) | byte[8] | Decoded | Context |
|-------|----------|---------|---------|---------|
| 3046  | 134.2    | 0xD1    | 74°F (23.3°C) | KJR decrease from 75°F |
| 3212  | 141.1    | 0xD0    | 73°F (22.8°C) | KJR decrease |
| 10723 | 471.6    | 0xD5    | 78°F (25.6°C) | IR set 78°F |
| 11887 | 522.7    | 0xD4    | 77°F (25.0°C) | IR 77°F |
| 12313 | 541.1    | 0x58    | 24°C (75.2°F) | IR→C, 24°C |

### XYE C6 FollowMe response byte[18] — mirrors setpoint

| Frame | Time (s) | byte[18] | Decoded |
|-------|----------|----------|---------|
| 2425  | 106.4    | 0xD0     | 73°F (22.8°C) — F mode |
| 3052  | 134.2    | 0xD1     | 74°F (23.3°C) — F mode |
| 6543  | 286.6    | 0x57     | 23°C (73.4°F) — C mode |
| 12319 | 541.2    | 0x58     | 24°C (75.2°F) — C mode |

### XYE D0 broadcast — same dual encoding, slower propagation

D0 byte[7] uses the same bit 7 unit flag as C0/C3/C6. The propagation delay
to D0 is longer: +5.4 s after the UART C/F switch (vs +3.3 s for C0).
Initial analysis incorrectly concluded D0 was Celsius-only — the check window
was too narrow. The full session timeline shows all 20 D0 byte[7] transitions
match the C0 byte[10] values (e.g. 0x57→0xD0 at t=29.9 s).

### XYE indoor/outdoor temperatures — unchanged in F mode

Byte-by-byte diff of XYE C0 32-byte response (baseline vs first F):

```
Byte:  [0] [1] .. [10] [11] [12] .. [30] [31]
C:      aa  c0     57   58   69      98   55
F:      aa  c0     d0   58   6b      1d   55
                   ★★        ★★      ★★
```

Only byte[10] changes due to C/F. Byte[12] change (0x69→0x6b) is outdoor
temperature drift, not C/F-related. Byte[30] is CRC recomputed.

### XYE C6 query byte[10] — not C/F-related

C6 16-byte query byte[10] values (0x42, 0x44, 0x46) vary independently of
C/F mode in both Celsius and Fahrenheit windows. Likely an operational or
addressing field.

---

## 4. Propagation timing: UART → R/T → XYE — **Confirmed**

Measured at the first C→F switch (Phase 2):

| Bus | Frame | Time (s) | Delay from UART | Event |
|-----|-------|----------|-----------------|-------|
| UART SET  | 556  | 24.53 | 0.0 s     | body[10] 0x00→0x04 |
| UART RSP  | 558  | 24.63 | +0.1 s    | 0xC0 confirms Unit: F |
| R/T 0xC0  | 615  | 27.10 | **+2.6 s**| Unit: F in status response |
| XYE C0    | 631  | 27.82 | **+3.3 s**| byte[10] 0x57→0xD0 |

Propagation order: **UART (0 s) → R/T (+2.6 s) → XYE (+3.3 s)**.

The R/T delay is within one polling cycle (~5.5 s). XYE follows ~0.7 s after
the R/T response, suggesting the display board updates the XYE bus after
processing the R/T status.

---

## 5. KJR-120M steps in 1°F increments in Fahrenheit mode — **Confirmed**

R/T setpoint transitions during KJR-120M operation in F mode (Phase 3):

| Time (s) | Setpoint (°C) | Setpoint (°F) | Step |
|----------|---------------|---------------|------|
| 119.2    | 24.0°C        | 75°F          | (app set) |
| 134.4    | 23.5°C        | 74°F          | -1°F → -0.5°C |
| 141.6    | 23.0°C        | 73°F          | -1°F → -0.5°C |

Each KJR-120M button press decrements by exactly 1°F. The Celsius-internal
encoding rounds each °F to the nearest 0.5°C: 73°F→23.0°C, 74°F→23.5°C,
75°F→24.0°C.

---

## 6. IR remote forces unit switch via temperature command — **Consistent**

There is no separate "unit switch" command from the IR remote. Instead, the
temperature command itself carries the unit implicitly:

- **IR in Celsius mode** sends a Celsius-encoded setpoint → the AC resets to
  Celsius display. Visible at t=182.6 s: R/T 0xC0 switches F→C with setpoint
  changing to 24°C (the operator pressed temp on the IR remote set to °C).

- **IR in Fahrenheit mode** sends a Fahrenheit-encoded setpoint → the AC
  switches to Fahrenheit display. Visible at t=471.8 s: R/T 0xC0 switches C→F
  with setpoint 25°C (78°F), matching the operator note "set to 78f".

The XYE bus confirms this mechanism: byte[10] transitions show the unit flag
changing simultaneously with the setpoint value (e.g. 0x57→0xD5 at t=472.3 s).

No UART command is generated for IR-initiated changes. The signal path is:
IR receiver → display board → R/T bus → XYE bus (bypassing UART/Wi-Fi entirely).

---

## 7. Follow Me temperature encoding unchanged in F mode — **Confirmed**

R/T 0x41 Follow Me temperature (body[5]) uses the formula `T_celsius × 2 + 50`
regardless of the display unit setting. All 10 Follow Me frames in the session
show body[5] = 0x62 (raw=98 → 24.0°C / 75.2°F), spanning both C and F mode
windows.

---

## 8. Display-mainboard bus: no clear C/F flag identified — **Hypothesis**

The disp-mainboard 0x20 Grey (display→mainboard) frame type does not contain
an identifiable C/F flag. Byte[16] of the 36-byte frame increments by 0x10 on
each set command event (sequence counter), but this does not distinguish between
C/F transitions and temperature-only changes. Other frame types (0x30, 0x31)
show normal operational parameter drift (compressor frequency, EEV position)
that does not correlate with C/F switching.

The dissector does not decode a unit field for disp-mainboard frames. Further
investigation with targeted captures (C/F switch only, no temperature change)
would be needed to identify whether the display-mainboard bus carries the unit
setting.

---

## Summary of temperature field behavior

### Fields unchanged by C/F switch (always Celsius-internal)

| # | Bus | Field | Formula | Evidence |
|---|-----|-------|---------|----------|
| 1 | UART/R/T | 0x40 body[2] setpoint | bits[3:0]+16+bit4×0.5 | 74°F→0x97=23.5°C, 75°F→0x88=24.0°C |
| 2 | UART/R/T | 0xC0 body[2] setpoint readback | same | mirrors SET values |
| 3 | UART/R/T | 0xC0 body[11] indoor T1 | (raw-50)/2 | raw=0x62=24.0°C throughout |
| 4 | UART/R/T | 0xC0 body[12] outdoor T4 | (raw-50)/2 | raw=0x39=3.5°C throughout |
| 5 | UART/R/T | 0xC0 body[13] temp override | raw °C | 0x0B=23°C, 0x0C=24°C |
| 6 | UART/R/T | 0xC0 body[15] temp decimals | nibbles, tenths | normal drift only |
| 7 | R/T | 0x41 body[5] Follow Me | T×2+50 | 0x62=24.0°C (all 10 frames) |
| 8 | R/T | 0xC1 grp1 T1 indoor coil | (raw-30)/2 | raw=78=24.0°C throughout |
| 9 | R/T | 0xC1 grp1 T4 outdoor | (raw-50)/2 | raw=57=3.5°C throughout |
| 10 | R/T | 0xC1 grp1 Tp discharge | raw °C | 32-34°C (compressor drift) |
| 11 | XYE | C0 byte[11] indoor | raw | 0x58-0x59 (actual temp drift) |
| 12 | XYE | C0 byte[12] outdoor | raw | 0x60-0x71 (gradual drift) |
### Fields that change in F mode

| # | Bus | Field | C encoding | F encoding |
|---|-----|-------|------------|------------|
| 13 | UART/R/T | 0x40/0xC0 body[10] bit 2 | 0 = Celsius | 1 = Fahrenheit |
| 14 | XYE | C0 byte[10] setpoint | bit7=0, T_C+0x40 | bit7=1, T_F+0x87 |
| 15 | XYE | C3 byte[8] setpoint | bit7=0, T_C+0x40 | bit7=1, T_F+0x87 |
| 16 | XYE | C6 resp byte[18] setpoint | mirrors C0 byte[10] | mirrors C0 byte[10] |
| 17 | XYE | D0 byte[7] setpoint | bit7=0, T_C+0x40 | bit7=1, T_F+0x87 (delay +5.4 s) |

---

## Dissector improvements identified — all implemented

1. **`decode_uart_40_set` body[10] bit 2**: Added "Unit: C/F" decode.
2. **XYE C0/C3 setpoint byte**: Added bit 7 unit flag decode with display-unit
   temperature.
3. **XYE C6 response byte[18]**: Added setpoint decode (mirrors C0 encoding).
4. **XYE D0 byte[7]**: Added bit 7 unit flag decode (same as C0/C3).
