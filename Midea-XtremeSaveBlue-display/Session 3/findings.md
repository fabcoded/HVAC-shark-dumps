# Session 3 — Findings

## Session context

First HAHB (RS-485 transceiver) capture session, simultaneously with the R/T CN1 bus.
Key discoveries: XYE C6 Follow-Me is a set-acknowledgment handshake (not a room temperature
push in this capture); setpoint changes on the HAHB bus are relayed to the CN1 R-T bus
within one polling slot; the display board broadcasts state via an unknown 0xD0 frame.

For operator setup and probe details, see [SessionNotes.md](SessionNotes.md).

---

## Buses captured

| Channel        | Direction             | Notes                              |
|----------------|-----------------------|------------------------------------|
| HAHB (XYE)     | Both (CH6 − CH7)      | Room controller ↔ display board    |
| HAHB "slave"   | MFB-X → display       | Room controller commands only      |
| R-T CN1        | Bidirectional         | Display board ↔ mainboard internal |

---

## 1. XYE polling cycle on HAHB — Confirmed

The room controller (KJR-12x) runs a fixed 3-command polling cycle at ~0.3 s intervals:

```
C4 ExtQuery  (M->S 16b) → C4 response (S->M 32b)     every ~1.8 s
C0 Query     (M->S 16b) → C0 response (S->M 32b)     every ~0.3 s
D0 broadcast (S->M 32b, no request)                   every ~0.3 s, interleaved
```

C0 responses are the primary status poll. C4 extended queries appear roughly every
6th cycle. No missing responses observed — the display unit answers every request.

---

## 2. Temperature encoding — **Hypothesis**

Three C3 Set commands were captured with decrementing setpoints (operator stepped
temperature down). Cross-referencing across all three buses:

| C3 byte[8] | Decoded (b8 − 0x40) | R-T byte[13] | D0 byte[7] |
|------------|---------------------|--------------|------------|
| `0x58`     | **24 °C**           | `0x88`       | `0x58`     |
| `0x57`     | **23 °C**           | `0x87`       | `0x57`     |
| `0x56`     | **22 °C**           | `0x86`       | `0x56`     |

- **XYE (HAHB) encoding:** `setT_byte = T_celsius + 0x40`
- **R-T CN1 encoding:** `setT_byte = T_celsius + 0x70` = XYE byte + 0x30
- **D0 encoding:** same as XYE (byte[7] = T + 0x40)

22–24 °C is plausible for a heating session. Offset 0x40 aligns with values
documented in some Midea reverse-engineering references.

**To confirm:** capture a session with operator-logged setpoints (e.g. set to 20 °C,
then 25 °C, then 30 °C) and verify the formula holds at the extremes.

---

## 3. XYE C6 Follow-Me — observed behavior **[Hypothesis]**

### 3.1 Occurrence pattern

C6 never occurs standalone. Every occurrence is part of a fixed atomic quadruplet:

```
C3 Set  (M->S 16b)  →  C3 Response  (S->M 32b)
C6      (M->S 16b)  →  C6 Response  (S->M 32b)
```

Three quadruplets were captured, all at setpoint changes. No C6 frame was observed
outside this context.

### 3.2 C6 master request — zero payload

```
AA C6 00 00 00 00  00 00 00 00  46 17 00 39 A4 55
                   ↑  ↑  ↑  ↑
                  b6 b7 b8 b9 = 0x00 — no room temperature present
```

The room controller does not embed a room temperature in the C6 request in this
capture. C6 here acts as a **follow-up handshake / state-echo request**, not as
a room temperature push (the "Follow-Me" function documented in ESPHome).

Whether the KJR-12x would populate bytes [6..9] with a measured room temperature
under different conditions (e.g. with an external sensor wired) is unknown.

### 3.3 C6 slave response — echoes current operating state

```
Frame 63  (after setT=0x58=24°C): AA C6 … 05 00 02 30 … 84 80 58 BC D6 … 3D 55
Frame 110 (after setT=0x57=23°C): AA C6 … 05 00 02 30 … 84 80 57 BC D6 … 3E 55
Frame 125 (after setT=0x56=22°C): AA C6 … 05 00 02 30 … 84 80 56 BC D6 … 3F 55
                                                          ↑  ↑  ↑           ↑
                                                       oper fan setT   rolling counter
```

| Field          | Position | Value       | Notes                              |
|----------------|----------|-------------|------------------------------------|
| flags?         | byte[6]  | `0x05`      | Constant — meaning unknown         |
| reserved       | byte[7]  | `0x00`      | Always zero                        |
| flags?         | byte[8]  | `0x02`      | Constant                           |
| unknown        | byte[9]  | `0x30`      | Constant                           |
| oper mode      | byte[16] | `0x84`      | Heat + Power on — mirrors C3 b6   |
| fan speed      | byte[17] | `0x80`      | Auto — mirrors C3 b7              |
| set temp       | byte[18] | tracks C3   | Changes with each C3 set command  |
| sensor T2A?    | byte[19] | `0xBC`      | Constant here                      |
| sensor T2B?    | byte[20] | `0xD6`      | Constant here                      |
| counter/CRC    | byte[30] | +1 per frame | 0x3D → 0x3E → 0x3F               |

The C6 response is structurally similar to a 32-byte C0 status response, but with
command byte 0xC6 and the set-state fields at different offsets. The rolling byte[30]
may be a sequence counter or a CRC that happens to increment linearly here.

---

## 4. 0xD0 — state broadcast (display → room controller) — **Hypothesis**

32-byte frames appear on the display→MFB-X channel (CH6 − CH7) every ~0.3 s,
not solicited by any request. Three distinct variants observed, differing only in
byte[7]:

```
AA D0 20 01 00  84  80  57  00 00 00 00 00 00 00 06 17 00 61 29 00 00 00 00 00 00 00 00 00 92 7B 55
AA D0 20 01 00  84  80  58  …
AA D0 20 01 00  84  80  56  …
                ↑   ↑   ↑
             oper  fan setT  (XYE T+0x40 encoding)
```

| Field    | Offset | Value  | Notes                                 |
|----------|--------|--------|---------------------------------------|
| oper     | [5]    | `0x84` | Heat + Power — constant in session    |
| fan      | [6]    | `0x80` | Auto — constant in session            |
| setT     | [7]    | varies | Tracks current setpoint (T + 0x40)    |
| unknown  | [15]   | `0x06` | Constant                              |
| unknown  | [16]   | `0x17` | Constant                              |
| unknown  | [18]   | `0x61` | Constant                              |
| unknown  | [19]   | `0x29` | Constant                              |

byte[7] updates immediately after each C3 Set is applied. All other bytes remain
constant throughout the session — they may encode additional state not exercised here
(e.g. timers, swing, error codes).

**Interpretation:** The display board continuously pushes its current operating state
to the room controller. The KJR-12x likely uses this to update its local display
without needing to poll.

---

## 5. R-T CN1 bus relays HAHB setpoint — **Confirmed** (3 instances)

Within one R-T polling slot of a HAHB C3 Set, the display board issues a 0x40 Set
command on the CN1 R-T bus carrying the same temperature (offset-adjusted):

| HAHB frame    | R-T frame     | Δt     | XYE byte[8] | R-T byte[13] | Relationship    |
|---------------|---------------|--------|-------------|--------------|-----------------|
| #59 @ 8.354s  | #60 @ 8.366s  | 12 ms  | `0x58`      | `0x88`       | R-T = XYE+0x30  |
| #106 @ 14.305s| #111 @ 14.536s| 231 ms | `0x57`      | `0x87`       | R-T = XYE+0x30  |
| #122 @ 15.836s| #132 @ 17.044s| 1.2 s  | `0x56`      | `0x86`       | R-T = XYE+0x30  |

The 12 ms case is within the same bus slot. The 231 ms and 1.2 s delays correspond
to the next available R-T polling window — the display board queues the relay.

R-T 0x40 Set frame structure (constant fields):
```
AA BC 22 AC 00 00 00 00 00 03 02  40  01  [setT]  66  00 00 00 30 80 …
                              ↑   cmd      ↑      ↑ mode?
                           group=0x02    temp   0x66 = ?
```

byte[14]=0x66 is constant across all three relayed set commands. Its meaning is
unknown — could encode mode, flags, or a fixed parameter for the 0x40 command type.

---

## 6. R-T CN1 group-page polling (0x41 / 0xC1)

The R-T bus runs a background group-page polling cycle alongside the set commands.
Page IDs observed in 0x41 queries and echoed in 0xC1 responses:

| Page (byte[13]) | Seen in     | Notes                            |
|-----------------|-------------|----------------------------------|
| `0xFF`          | 0x41 query  | Status query (→ 0xC0 response)  |
| `0x41`          | 0x41 + 0xC1 | Group 1 page — data in response |
| `0x42`          | 0x41 + 0xC1 | Group 2 page — data in response |
| `0x43`          | 0x41 + 0xC1 | Group 3 / page 3                |

Group-page response payloads (0xC1 frames) are not yet decoded. They contain
multi-byte data fields that may include sensor readings, error registers, or
configuration parameters. This is the CN1 equivalent of the HAHB C4 ExtQuery
cycle.

---

## 7. Follow-Me cross-bus correlation — **Hypothesis**

Follow-Me (Called bodySense?) is a two-step mechanism on the UART bus (from mill1000/Finding 10):
1. **Enable:** `0x40` Set with `body[8] bit 7 = 0x80` (`bodySense`)
2. **Temperature:** `0x41` extended frame, `body[4]=0x01` (optCommand), `body[5] = T_celsius × 2 + 50`

### What Session 3 shows

**R-T CN1 0x40 frames have `body[8]=0x80` (Follow-Me enable) in every Set command:**
```
body[8] = 0x80   ← bodySense bit set → Follow-Me active
```
Follow-Me was enabled on this hardware when the session was captured.

**No `0x41` optCommand=0x01 (room-temperature) frames observed on the R-T bus.**
The Wi-Fi UART bus (CN3) was not probed in Session 3, so the UART room-temperature
frame from the phone/app may be occurring there unseen.

### XYE C6 as the Follow-Me mechanism on HAHB

| Bus | Frame | Role |
|-----|-------|------|
| HAHB XYE | `C3` M→S | Carries temperature in byte[8]; during Follow-Me this may be the room temperature, not a user setpoint |
| HAHB XYE | `C6` M→S | Follow-Me handshake — zero payload; flags the preceding C3 as a Follow-Me frame |
| HAHB XYE | `C6` S→M | Unit echoes oper+fan+setT at response bytes[16..18]; confirms Follow-Me accepted |
| R-T CN1 | `0x40` body[8]=0x80 | Display relays Follow-Me enable to mainboard (UART equivalent of XYE C6) |

The XYE C6 request carries **no room temperature in its payload** in this capture (bytes [6..9] = 0).
The temperature is carried in the C3 byte[8] that immediately precedes every C6.
C6 is the flag that marks the preceding C3 as a Follow-Me temperature push rather than a user-set command.
This is structurally analogous to UART `body[8]=0x80` in the 0x40 frame enabling the `0x41` temperature.

**C6 response byte[30] is a rolling counter** (0x3D → 0x3E → 0x3F across the three observations).

### Open question: C3 byte[8] = room temperature or setpoint?

The session notes do not log what the room temperature or setpoint was. The three
values 0x58/0x57/0x56 decode to 24/23/22 °C if the offset is 0x40. These decrement
monotonically — consistent with either a cooling room or a user stepping the setpoint down.

**To resolve:** capture a session where room temperature and setpoint are logged separately.
If Follow-Me is active and the room is at 22 °C while the setpoint is 24 °C, check which
value appears in C3 byte[8].

---

## Open questions

| Question | What to capture |
|---|---|
| Temperature encoding: confirm T+0x40 at boundary setpoints | Logged session at 16 °C and 30 °C |
| C3 byte[8] during Follow-Me = room temp or setpoint? | Session with known room temp ≠ setpoint, Follow-Me active |
| Does Wi-Fi UART also send 0x41 optCmd=0x01 simultaneously? | Repeat with CN3 probed alongside HAHB |
| C6 with non-zero room temperature payload — does KJR-12x ever use it? | KJR with external sensor, or ESPHome C6 injection |
| 0xD0 bytes [15..28] — what fields change with mode/fan/swing? | Session with explicit mode and fan changes |
| R-T 0x40 body[3]=0x66 — encodes mode? | Capture with Cool/Heat/Fan mode switching |
| R-T 0xC1 group-page payloads — field layout | Systematic decode against known values |
