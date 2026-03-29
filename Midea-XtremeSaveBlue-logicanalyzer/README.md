# Midea XtremeSaveBlue — Display Board Captures

> **Hardware identification note**: "Midea XtremeSaveBlue" is used here solely as
> the identifier for the specific test device under investigation. The brand and
> product name are the property of their respective owners; their use is purely
> descriptive and does not imply any affiliation or endorsement.

Capture sessions from the display board of a **Midea XtremeSaveBlue** split unit
(test object). Logic analyser probes are attached to the display board's internal buses.

---

## Hardware identification

| Field              | Value                              | Source         |
|--------------------|------------------------------------|----------------|
| Name               | Split-Typ Klimaanlage              | Cloud API      |
| Model code (sn8)   | `00000Q11`                         | Cloud API      |
| Model number       | `44204`                            | Cloud API      |
| Smart product ID   | `10006474`                         | Cloud API      |
| Serial number      | `000000P0000000Q11841C3CEBD9A0000` | Cloud API      |
| Appliance type     | `172` = `0xAC`                     | Cloud API + **Confirmed in all UART/R-T captures** |
| Wi-Fi module MAC   | `18:41:C3:CE:BD:9A`                | Derived from SN (bytes 17–28) |

### Appliance type `0xAC` — confirmed on all local buses

The cloud-reported `type: 172 = 0xAC` matches exactly:
- UART frames: `byte[2] = 0xAC` (appliance type field, every frame)
- R/T frames: `byte[3] = 0xAC` (appliance type field, every frame)

This cross-confirms the `0xAC` field is not just convention but device-specific.

### SN and model in captures

- `sn8: 00000Q11` — carried in UART `0x07` device-identification frames. In Sessions
  2 and 4, the `0x07` body contains all `0xFF` (no SN transmitted in these sessions).
- `model_number: 44204` — not observed directly in local bus captures; cloud-side only.
- `smart_product_id / sn` — cloud-side only; do not appear on UART, XYE, or R/T buses.

---

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

- **Unit**: Midea XtremeSaveBlue (split A/C), model `00000Q11`
- **Capture point**: Display board (CN1, CN3, IR receiver)
- **Analyser**: Saleae Logic

## Buses captured

| Bus                   | Connector | Direction      | Protocol                                       |
|-----------------------|-----------|----------------|------------------------------------------------|
| R/T ext. board        | CN1       | Bidirectional  | HA/HB framing, UART-compatible body commands   |
| Wi-Fi module          | CN3       | Bidirectional  | Midea UART (SmartKey)                          |
| Mainboard internal    | CN1 grey/blue | Bidirectional | Display–mainboard proprietary (AA 20/30/31)  |
| IR receiver           | —         | Receive only   | Midea IR (NEC-like, 48-bit frames)             |

## Session file conventions

Each session folder contains:

| File              | Contents                                                         |
|-------------------|------------------------------------------------------------------|
| `SessionNotes.md` | Operator log — initial state, sequence of actions, frame timestamps. Ground truth for correlating frames to known actions. |
| `findings.md`     | Analysis output — field encoding tables, confidence levels, open questions, conclusions. |
| `channels.yaml`   | Channel configuration for the pcap converter (bus types, CSV mapping). |
| `Session N.csv`   | Pre-decoded Saleae Logic export (input to converter).            |
| `session.pcap`    | Converted pcap, loadable in Wireshark with the HVAC-shark dissector. |

**Note on cut-off packets**: The first packet(s) in a capture session may be
truncated or show CRC/checksum errors. This happens when the logic analyser
begins recording mid-frame — the converter outputs the partial frame data as-is.
These are not protocol errors but capture artefacts; they can be safely ignored.

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

### Session 5

Buses captured: HAHB RS-485 (XYE), CN1 R-T bidirectional, CN3 Wi-Fi UART, CN1 mainboard UART.

- [SessionNotes.md](Session%205/SessionNotes.md)
- [channels.yaml](Session%205/channels.yaml)

### Session 6

**Key finding**: Service menu ground truth. Sensor temperatures read directly from the
display PCB service menu: Tp = 74 °C, T1 = 18 °C, T3 = 2 °C, T4 = 4 °C. Cross-validates
the XYE `(raw − 40) / 2` temperature formula and confirms UART R/T body[14] = Tp in direct
integer °C. Also exposed the Session 3 misidentification of XYE byte[19] as Tp — byte[19]
is a fixed device-type field (`0xBC`); actual Tp is at byte[22].

Buses captured: HAHB RS-485 (XYE), CN1 R-T bidirectional, CN3 Wi-Fi UART, CN1 mainboard UART.

- [SessionNotes.md](Session%206/SessionNotes.md)
- [channels.yaml](Session%206/channels.yaml)

### Session 7

**Key finding**: Full mode sweep (Heat → Cool → Dry → Fan → Auto) with single-step
setpoint transitions 16–30 °C. Mode byte values confirmed for all modes. Minimum setpoint
16 °C and maximum setpoint 30 °C confirmed. Follow-Me disabled at end of session.

Buses captured: HAHB RS-485 (XYE), CN1 R-T bidirectional, CN1 mainboard UART.
Wi-Fi module removed.

- [SessionNotes.md](Session%207/SessionNotes.md)
- [channels.yaml](Session%207/channels.yaml)

### Session 8

**Key finding**: Swing and vane position investigation. Swing on/off via both KJR-12x
wired controller and app (Wi-Fi). Fixed vane positions (5 vertical + 5 horizontal) via
app only. Power consumption (Group 4) frames captured and decoded — BCD encoding confirmed
(113.81 kWh cumulative, 381.4 W real-time). Wi-Fi stick connected.

Buses captured: HAHB RS-485 (XYE), CN1 R-T bidirectional, CN3 Wi-Fi UART, CN1 mainboard UART.

- [SessionNotes.md](Session%208/SessionNotes.md)
- [channels.yaml](Session%208/channels.yaml)

### Session 9

**Key finding**: Cold-boot capture with no Wi-Fi module. Captures the full power-on
initialisation sequence including the rare mainboard `AA 50` init frame (confirmed boot-
specific), bus sync `0xFF` bytes, and the first R/T handshake. Mode sweep: Fan/Off
(`0x00`) → Dry (`0x81`) → `0x91` (unidentified) → Cool (`0x82`) → Heat (`0x84`).
Mode `0x91` is a new unconfirmed code, possibly an Auto variant.

Buses captured: HAHB RS-485 (XYE), CN1 R-T bidirectional, CN3 Wi-Fi UART (no dongle —
mainboard heartbeat only), CN1 mainboard UART.

- [SessionNotes.md](Session%209/SessionNotes.md)
- [channels.yaml](Session%209/channels.yaml)
