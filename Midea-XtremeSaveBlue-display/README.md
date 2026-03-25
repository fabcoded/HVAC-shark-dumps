# Midea extremeSaveBlue — Display Board Captures

> **Hardware identification note**: "Midea extremeSaveBlue" is used here solely as
> the identifier for the specific test device under investigation. The brand and
> product name are the property of their respective owners; their use is purely
> descriptive and does not imply any affiliation or endorsement.

Capture sessions from the display board of a **Midea extremeSaveBlue** split unit
(test object). Logic analyser probes are attached to the display board's internal buses.

## Analysis policy — best effort, controversies explicit

All protocol analysis in this repository is best-effort, derived from captures,
open-source reference implementations, and community notes. No official Midea
specification is available.

**Every claim must carry a confidence label:**

| Label           | Meaning                                                                |
|-----------------|------------------------------------------------------------------------|
| **Confirmed**   | Multiple independent data points or hardware-verified                  |
| **Consistent**  | Own captures agree with at least one external source                   |
| **Hypothesis**  | Own captures only, not independently verified                          |
| **Disputed**    | Sources or captures contradict each other — conflict stated explicitly |
| **Unknown**     | Insufficient data                                                      |

When external sources (IRremoteESP8266, ESPHome, community posts) conflict with
own captures, **both interpretations are documented**, not resolved by assumption.
A discrepancy is only closed after a dedicated capture session that was designed
to test it.

---

## Hardware

- **Unit**: Midea extremeSaveBlue (split A/C)
- **Capture point**: Display board (CN1, CN3, IR receiver)
- **Analyser**: Saleae Logic

## Buses captured

| Bus            | Connector | Direction      | Protocol          |
|----------------|-----------|----------------|-------------------|
| R/T ext. board | CN1       | Bidirectional  | HA/HB framing, UART-compatible body commands |
| Wi-Fi module   | CN3       | Bidirectional  | Midea UART (SmartKey) |
| IR receiver    | —         | Receive only   | Midea IR (NEC-like, 48-bit frames) |

## Session file conventions

Each session folder contains:

| File              | Contents                                                         |
|-------------------|------------------------------------------------------------------|
| `SessionNotes.md` | Operator log — initial state, sequence of actions, frame timestamps. Ground truth for correlating frames to known actions. |
| `findings.md`     | Analysis output — field encoding tables, confidence levels, open questions, conclusions. |
| `channels.yaml`   | Channel configuration for the pcap converter (bus types, CSV mapping). |
| `Session N.csv`   | Pre-decoded Saleae Logic export (input to converter).            |
| `session.pcap`    | Converted pcap, loadable in Wireshark with the HVAC-shark dissector. |

## Sessions

### Session 1

**Key finding**: The R/T extension board bus (CN1) carries UART-compatible body
commands over HA/HB framing — establishing the link between the R/T pin and the
Midea UART protocol on this hardware platform.

Buses captured: R/T extension board, Wi-Fi module (UART), mainboard UART (CN1 grey/blue).
No IR capture. Passive observation session — no deliberate operator actions.

- [SessionNotes.md](Session%201/SessionNotes.md)
- [findings.md](Session%201/findings.md)
- [channels.yaml](Session%201/channels.yaml)

### Session 2

**Key finding**: First IR decode. The Midea remote uses a NEC-like 48-bit IR protocol
with three frame types: `0xB2` (AC control), `0xB9` (installer/setter mode), `0xD5`
(follow-up). Temperature encoding confirmed for 22, 24, 26 deg C. Several fields
remain open (byte[2] mode/fan bits, bit4 swing identity).

Buses captured: R/T extension board, Wi-Fi module (UART), IR receiver (raw).

- [SessionNotes.md](Session%202/SessionNotes.md)
- [findings.md](Session%202/findings.md)
- [channels.yaml](Session%202/channels.yaml)

### Session 3

**Key findings**: First direct HAHB (RS-485 transceiver) capture alongside CN1 R-T bus.
XYE C6 Follow-Me observed as a set-acknowledgment handshake (C3+C6 pair, not standalone
room temperature push). Temperature encoding hypothesis: XYE setT = T + 0x40; R-T setT =
T + 0x70. Setpoint changes on HAHB relay to CN1 R-T within one polling slot. Unknown 0xD0
broadcast frame identified as display→room-controller state push.

Buses captured: HAHB RS-485 (XYE, both directions), CN1 R-T bidirectional.

- [SessionNotes.md](Session%203/SessionNotes.md)
- [findings.md](Session%203/findings.md)
- [channels.yaml](Session%203/channels.yaml)

### Session 4

**Key opportunities**: First full all-bus capture (HAHB + R-T CN1 + Wi-Fi UART CN3 +
mainboard UART CN1 simultaneously). Includes power-on sequence from cold start. Known
operator actions: Heat mode throughout; setpoint 22→23→24→25 °C; fan Auto→Low→Mid→High→Auto.
Follow-Me active at 13 °C (KJR-12x internal sensor) throughout — first session where
UART 0x41 Follow-Me frames and XYE C6 frames can be correlated on the same timeline.
No findings yet.

Buses captured: HAHB RS-485 (XYE), CN1 R-T bidirectional, CN3 Wi-Fi UART, CN1 mainboard UART.

- [SessionNotes.md](Session%204/SessionNotes.md)
- [channels.yaml](Session%204/channels.yaml)
