# Session 6 — Session Notes (Operator Log)

Ground truth for correlating captured frames to known hardware setup and context.
For analysis results, see findings.md (not yet written).

---

## Hardware under test

- **Unit**: Midea extremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 4/5 — all internal display board buses simultaneously:
  HAHB RS-485 transceiver (adapter board), R/T CN1 bidirectional,
  Wi-Fi module CN3 UART, mainboard UART CN1 grey/blue
- **Logic analyser**: Saleae

---

## Probe setup

See [Session 4 channels.yaml](../Session%204/channels.yaml) as the reference.
Session 6 uses the identical channel configuration; see `channels.yaml` in this folder.

---

## Service menu readings (ground truth)

The display PCB service menu was accessed during this session, providing exact sensor
temperatures independent of bus encoding. These are the primary ground-truth values for
validating the XYE sensor byte formula `(raw − 40) / 2.0`.

| Service menu label          | Value   | Notes                                          |
|-----------------------------|---------|------------------------------------------------|
| Tp — compressor temperature | **74 °C** | High-side compressor thermistor               |
| T1 — indoor air (Follow-Me) | **18 °C** | KJR-12x wall controller sensor, Follow-Me ref |
| T3 — outdoor coil           | **2 °C**  | Outdoor unit coil thermistor                  |
| T4 — outdoor ambient        | **4 °C**  | Outdoor ambient air temperature               |

> T1 labelled "tindoor air (followme??)" by operator — confirmed as Follow-Me reference
> (KJR-12x internal sensor), not the indoor unit's own air thermistor.
> T4 labelled "toutside" — outdoor ambient, appears in XYE C4 ExtQuery response and R-T 0xC0.

Expected raw byte values (formula: `raw = T × 2 + 40`):

| Temperature | °C | Expected raw | Expected hex |
|-------------|-----|-------------|--------------|
| T1 indoor air | 18 | 76 | `0x4C` |
| T3 outdoor coil | 2 | 44 | `0x2C` |
| T4 outdoor ambient | 4 | 48 | `0x30` |
| Tp compressor | 74 | 188 | `0xBC` |

---

## Initial state (at capture start)

- **System power**: ON (running — exact prior state not logged)
- **Mode**: not logged — check capture
- **Setpoint**: not logged — check capture
- **Fan**: not logged — check capture
- **Follow-Me**: assumed active (KJR-12x connected)

---

## Operator action sequence

| Step | Action                                    | Expected state after        |
|------|-------------------------------------------|-----------------------------|
| 1    | Recording started with system running     | (state from prior session)  |
| 2    | Service menu accessed on display PCB      | Sensor readings observed    |
| 3    | Service menu values recorded (see above)  | Ground truth established    |
| 4    | (further actions not logged)              |                             |

---

## Key analysis opportunities in this session

- **Formula cross-validation (primary purpose)**: Service menu provides exact °C values.
  XYE 0xC0 response bytes at positions 11–14 (T1, T2A, T2B, T3) should decode via
  `(raw − 40) / 2.0` to match the service menu readings exactly.
  - T1 = 18 °C → expect `0x4C` in XYE 0xC0 byte[11]
  - T3 = 2 °C → expect `0x2C` in XYE 0xC0 byte[14]

- **T4 outdoor ambient location**: Service menu shows T4 = 4 °C. This value should appear in
  the XYE C4 ExtQuery response (not the regular C0 response) and in the R-T UART 0xC0
  Outdoor Temp field (`raw = 4 × 2 + 50 = 58 = 0x3A`).

- **Tp compressor temperature**: 74 °C appears in the C6 response at byte[19] (`0xBC` = 188).
  Session 3 findings noted byte[19] = `0xBC` as constant — this session confirms it encodes
  Tp using the same `(raw − 40) / 2.0` formula: `(0xBC − 40) / 2 = (188 − 40) / 2 = 74 °C`.

---

## Open questions this session should address

- Do XYE 0xC0 response bytes [11] and [14] decode to exactly 18 °C and 2 °C
  with formula `(raw − 40) / 2.0`? (Final confirmation of sensor byte formula.)
- Where does T4 = 4 °C appear in the captured frames? (C4 ExtQuery? R-T 0xC0? Both?)
- Is Tp = 74 °C (`0xBC`) consistently present in XYE C6 response byte[19] or C4 response?
- What was the active setpoint and mode — visible in C3 byte[8] and C6 byte[18]?
