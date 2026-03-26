# Session 9 — Session Notes (Operator Log)

Cold-boot capture with no Wi-Fi module. Primary value: captures the full power-on
initialisation sequence (bus sync, mainboard AA 50 init frame, first R/T handshake,
first XYE C0 response) and a mode sweep from Fan/Off → Dry → 0x91 → Cool → Heat.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 4–8 — all internal display board buses
  simultaneously: HAHB RS-485 (adapter board), R/T CN1 bidirectional,
  Wi-Fi module CN3 UART, mainboard UART CN1 grey/blue
- **Logic analyser**: Saleae
- **Wi-Fi stick**: NOT CONNECTED (removed for this session)
- **Wired controller**: KJR-12x

---

## Probe setup

Same channel configuration as Sessions 4–8. See `channels.yaml` in this folder.

---

## Initial state (at capture start)

System was powered off (hard power cut). Recording started before power-on.

- **System power**: OFF at capture start → powered on during capture
- **Mode at first C0 response** (t ≈ 6 s): `0x00` — Fan/Off (unset post-boot state)
- **Setpoint at first C0**: 21 °C (`0x55`)
- **Fan at first C0**: Auto (`0x80`)

---

## Operator action sequence

| Step | Time (approx) | Action                             | Expected state after         |
|------|---------------|------------------------------------|------------------------------|
| 1    | t = 0 s       | Recording started, unit powered off | Bus sync bytes visible       |
| 2    | t ≈ 0.9 s     | Unit powered on via mains          | Boot init frames on all buses|
| 3    | t ≈ 6 s       | Unit active, no input yet          | Mode=0x00 / 21 °C / Fan Auto |
| 4    | t ≈ 9 s       | Mode button → Dry                  | Dry (`0x81`) / 21 °C         |
| 5    | t ≈ 12 s      | Mode button → (next mode)          | Mode `0x91` / 21 °C          |
| 6    | t ≈ 13 s      | Mode button → Cool                 | Cool (`0x82`) / 21 °C        |
| 7    | t ≈ 15 s      | Mode button → Heat                 | Heat (`0x84`) / 21 °C        |
| 8    | t ≈ 16 s      | Setpoint +1 °C                     | Heat / 22 °C                 |
| 9    | t ≈ 16 s      | Setpoint +1 °C                     | Heat / 23 °C                 |
| 10   | t ≈ 83 s      | Recording stopped                  | Heat (`0x84`) / 23 °C        |

> Mode cycling was rapid (< 2 s per step). The operator cycled through modes using
> the KJR-12x mode button. The intermediate mode `0x91` appeared between Fan-cycle
> and Cool — exact button label is unknown; decode from C3 Set sequence in capture.

---

## Session statistics (from pcap)

- **Duration**: ~83 seconds (1.4 minutes)
- **Total frames by bus**:
  - XYE (HAHB): 432
  - UART: 24
  - DISP-MB (mainboard): 1244
  - R/T: 172 (85 requests + 86 responses + 1 sync byte)

### XYE frame breakdown

| Command | Count | Notes                                        |
|---------|-------|----------------------------------------------|
| C0      | 92    | Status response                              |
| C3      | 12    | Set commands (6 mode/setpoint changes × 2)  |
| C4      | 237   | ExtQuery response                            |
| C6      | 12    | Extended status response                     |
| D0      | 79    | Wall-controller status                       |

### UART frame breakdown

No Wi-Fi dongle → no 0x41 (Query) or 0x40 (Set) commands. Observed frames are the
mainboard's background heartbeat, transmitted regardless of dongle presence.

| Msg type | Count | Notes                                        |
|----------|-------|----------------------------------------------|
| 0x04     | 19    | C1 sub-body responses (A0, A1, A2, A3, A5, A6) — mainboard heartbeat |
| 0x05     | 4     | Handshake / ACK                              |

---

## Boot sequence detail (key frames)

The cold-boot sequence is the primary unique contribution of this session.
All timestamps are relative to capture start.

| t (s)  | Bus      | Frame                          | Significance                            |
|--------|----------|--------------------------------|-----------------------------------------|
| 0.00   | R/T      | `0xFF`                         | Bus sync byte — line noise at power-on  |
| 0.00   | UART     | `0xFF`                         | Bus sync byte                           |
| 0.03   | DISP-MB  | `0xFF`                         | Bus sync byte                           |
| 0.85   | DISP-MB  | `AA FF 0A 95 E7 0F 59 01 31 E1`| Anomalous frame — only at boot (also Session 4) |
| 0.88   | R/T      | `AA BC 22 AC … 03 41 81 00 FF …` | First R/T frame: 0x41 init request    |
| 0.88   | DISP-MB  | `AA FF 0A …`                   | Second AA FF frame                      |
| 0.93   | DISP-MB  | `AA 50 15 06 … AB EA`          | **Init query** (rare; only boot)        |
| 0.98   | DISP-MB  | `AA 50 40 96 04 20 00 0C …`    | **Init response** (64 bytes)            |
| 1.08   | DISP-MB  | `AA 20 24 …`                   | First regular status response           |
| 2.70   | XYE      | `AA C4 00 00 00 00 A5 5A …`    | First XYE C4 (short, 16-byte boot form) |
| 5.96   | XYE      | `AA C0 … 00 00 55 55 57 …`     | First full C0: mode=0x00 / 21 °C        |

The `AA 50` mainboard frame pair at t ≈ 0.93 s appears to be a boot/init exchange.
It was observed exactly twice across all 9 sessions — both in this session at power-on.
The `AA FF` frames were also observed only in Sessions 4 and 9. The correlation with
cold-boot events strongly suggests these are power-on initialisation artefacts.

---

## Mode byte `0x91` — new observation

The C0 response at t ≈ 12.2 s shows mode byte `0x91`. This value has not appeared in
any prior session. The known mode map from Sessions 3–8:

| Byte  | Mode  | Confirmed sessions |
|-------|-------|--------------------|
| `0x84`| Heat  | 3–9               |
| `0x82`| Cool  | 7                  |
| `0x81`| Dry   | 7, 9               |
| `0x80`| Fan   | 7, 8               |
| `0x90`| Auto  | 8                  |
| `0x91`| ?     | **9 only**         |

`0x91` appeared in the C3 Set command immediately before the corresponding C0 response,
so it was deliberately set by the controller. It may be a variant of Auto mode
(`0x90` + flag bit 0), or a transitional code generated during rapid mode cycling.
Cross-reference with the KJR-12x button sequence to identify.

---

## Key analysis opportunities

1. **Boot initialisation sequence**: The `AA FF` and `AA 50` mainboard frames are
   now confirmed as boot-specific (t < 1 s after power-on). Correlate the `AA 50`
   response payload bytes with the system clock or firmware version if possible.

2. **Mode byte `0x91`**: Only appearance in the dataset. The C3 Set command at t ≈ 11.8 s
   contains `0x91` — decode which KJR-12x button or mode name produces this value.

3. **UART without dongle**: All 24 UART frames originate from the mainboard itself.
   Sub-body types A0, A1, A2, A3, A5, A6 are all visible in the heartbeat cycle.
   A5 at t ≈ 39.4 s contains non-zero payload — compare to Session 8 for content.

4. **First C4 frame format**: The first C4 at t = 2.70 s is only 16 bytes
   (`AA C4 00 00 00 00 A5 5A 00 00 00 00 00 3B 02 55`) — a shorter form than the
   standard 32-byte response. May be a boot-state C4 before the outdoor unit is ready.

5. **R/T boot handshake**: The first R/T request at t = 0.88 s is a 38-byte 0x41 frame —
   unusually long compared to the standard 10-byte R/T 0x41 query. Likely a full-init
   version of the request sent only at power-on.
