# Session 13 — Findings

## Session context

Short unstructured session (~140 s, "just some random stuff"). All control via IR
remote — no UART SET commands (app not used for control). Provides critical new IR
protocol data: byte[2] varies across 4 distinct values, D5 byte[1] varies, and
byte[4] bits[3:0] takes yet more values.

For operator notes, see [SessionNotes.md](SessionNotes.md).

---

## Buses captured

| Channel               | Frames  |
|-----------------------|---------|
| UART (Wi-Fi CN3)      | 31      |
| R/T (CN1 ext board)   | 255     |
| XYE (HAHB RS-485)     | 709     |
| disp-mainboard (CN1)  | 2,100   |
| IR                    | 12      |

Total: 3,107 frames over 139.7 s (~2.3 min).

---

## 1. IR B2 byte[2] is NOT constant — **Disputed** (overrides protocol_ir.md)

protocol_ir.md documented byte[2] as "0xBF observed in all Session 2 frames
(Heat + Auto fan + Power ON)". Session 13 shows **four distinct byte[2] values**:

| t (s) | byte[2] | byte[4] | XYE mode after | Complement OK? |
|-------|---------|---------|---------------|----------------|
| 1     | 0xBF    | 0xE4    | 0x84 (Heat)   | yes |
| 19    | **0xFF** | 0xE4   | 0x81 (Auto)   | yes |
| 129   | **0x1F** | 0x48   | (no change)   | yes |
| 131   | **0xFF** | 0x4C   | 0x94 (Auto sub) | yes |
| 133   | **0x7B** | 0xE0   | 0x00 (OFF)    | yes |

All complement checks pass — these are valid frames, not corruption.

### byte[2] bit-level observations

| byte[2] | binary   | bit 7 | bits[6:4] | bits[3:0] | XYE result |
|---------|----------|-------|-----------|-----------|------------|
| 0xBF    | 10111111 | 1     | 011       | 1111      | Heat mode, ON |
| 0xFF    | 11111111 | 1     | 111       | 1111      | Auto mode, ON |
| 0x1F    | 00011111 | 0     | 001       | 1111      | (no mode change) |
| 0x7B    | 01111011 | 0     | 111       | 1011      | Power OFF |

Tentative interpretation:
- **bit 7** may be power flag (1=ON for 0xBF/0xFF, 0=OFF for 0x1F/0x7B where
  0x7B causes power-off). But 0x1F at t=129 did NOT cause power-off — unclear.
- **bits[6:4]**: 011=Heat (0xBF), 111=Auto (0xFF). 0x1F has 001 — unknown.
- **bits[3:0]**: 1111 in most frames (auto fan?), 1011 in 0x7B (different fan?).

Combined with Session 2 (only 0xBF), Session 10 (only 0xBF), and Session 12
(only 0xBF): **byte[2] = 0xBF is the Heat+Auto+ON default**. Other values
encode different modes and power states. Full decoding requires captures with
each mode (Cool, Dry, Fan) via IR.

---

## 2. IR B2 byte[4] bits[3:0] — more values observed

| Session | byte[4] bits[3:0] values | Mode |
|---------|-------------------------|------|
| 2       | 0xC only                | Heat |
| 10      | 0xC only                | Heat |
| 12      | 0x0 only                | Cool |
| **13**  | **0x4, 0x8, 0xC, 0x0**  | Heat/Auto/OFF |

Session 13 alone shows 4 different lower nibble values. Combined with all
sessions: 0x0, 0x4, 0x8, 0xC — a 4-value set using bits[3:2]:

| bits[3:2] | Value | Sessions |
|-----------|-------|----------|
| 00        | 0x0   | S12, S13 |
| 01        | 0x4   | S13 |
| 10        | 0x8   | S13 |
| 11        | 0xC   | S2, S10, S13 |

The lower nibble encodes operational state, not a fixed marker. The exact
mapping (mode? fan? swing?) is not yet determined.

---

## 3. D5 follow-up byte[1] varies — **Disputed** (overrides protocol_ir.md)

protocol_ir.md documented D5 byte[1] as "0x66 (non-standard)". Session 13 shows
two new values:

| t (s) | D5 raw         | byte[1] | byte[0]^byte[1] |
|-------|----------------|---------|------------------|
| 19    | D514000000E9   | **0x14** | 0xC1 |
| 129   | D5650000003A   | **0x65** | 0xB0 |
| 131   | D514000000E9   | 0x14    | 0xC1 |

Previous sessions: byte[1] always 0x66 (0xD5^0x66 = 0xB3).

The D5 byte[1] may depend on which B2 byte[2] value preceded it:
- After B2 byte[2]=0xFF → D5 byte[1]=0x14
- After B2 byte[2]=0x1F → D5 byte[1]=0x65

All D5 byte[3] = 0x00 (Celsius). The C/F flag interpretation from Session 10
still holds.

---

## 4. First B2 frame (t=1 s) — incomplete transmission

Frame 36 (t=1 s) is a single B2 frame with no repeat and no D5 follow-up.
This suggests an interrupted or partial IR transmission — the operator may have
briefly pointed the remote or pressed a button without completing the action.

---

## 5. XYE mode transitions via IR — **Confirmed S13**

| Time (s) | XYE byte[8] | Mode | IR command preceding |
|----------|-------------|------|---------------------|
| 0        | 0x84        | Heat | (initial state) |
| 21       | **0x81**    | Auto | IR byte[2]=0xFF at t=19 |
| 131      | **0x94**    | Auto (sub-mode) | IR byte[2]=0xFF at t=131 |
| 135      | **0x00**    | OFF  | IR byte[2]=0x7B at t=133 |

XYE byte[10] stays 0x58 (24 C) throughout — no setpoint changes from IR in
this session (only mode changes).

Mode 0x81 (Auto) and 0x94 (Auto with sub-mode flags) confirmed to be triggered
by IR byte[2]=0xFF. Power-off triggered by IR byte[2]=0x7B.

---

## 6. No UART SET commands

The 31 UART frames are all responses/heartbeats (0x03, 0x04, 0x05, 0x63, 0xA0,
0x0D) — zero 0x02 (Command). The app was not used for control. All state changes
came via IR remote, visible on the R/T and XYE buses.
