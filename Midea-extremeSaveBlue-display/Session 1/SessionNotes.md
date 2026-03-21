# Session 1 — Session Notes (Operator Log)

Ground truth for correlating captured frames to known hardware setup and context.
For analysis results, see [findings.md](findings.md).

> **Note**: this was a **passive observation session** — no deliberate operator
> actions were performed during the capture. The AC unit ran in its pre-existing
> state throughout. Initial AC state (mode, fan, temperature) was not logged.

---

## Hardware under test

- **Unit**: Midea extremeSaveBlue split A/C
- **Capture point**: Display board internal buses (CN1, CN3)
- **Logic analyser**: Saleae

---

## Probe setup

Four channels probed simultaneously on the display board:

| Channel name (CSV)          | Connector | Wire       | Direction            | Bus type       |
|-----------------------------|-----------|------------|----------------------|----------------|
| `mainboardGrey`             | CN1       | Grey       | Mainboard RXD        | disp-mainboard |
| `mainboardBlue`             | CN1       | Blue       | Mainboard TXD        | disp-mainboard |
| `bidirectionalExtensionBoard` | CN1     | R/T pin    | Bidirectional (half-duplex) | r-t       |
| `wifiBrown`                 | CN3       | Brown      | Wi-Fi module RX (display -> wifi) | uart |
| `wifiOrange`                | CN3       | Orange     | Wi-Fi module TX (wifi -> display) | uart |

### Extension board: MFB-X

The R/T pin on CN1 connects to an **MFB-X** converter module, which bridges the
single-wire half-duplex R/T signal to an **HA/HB differential bus** running toward
the mainboard. The capture probes the single-ended side of the R/T wire (before
the MFB-X converter).

The HA/HB bus on the other side of the MFB-X was connected to a **KJR-120M/BGEF**
wall controller (Midea wired remote panel).

> The **MFB-C** module (used for XYE RS-485 bus) was not connected in this session.
> XYE capture is planned for a future session.

---

## Session context

- **AC state at session start**: unknown — not logged
- **Operator actions during session**: none (passive observation)
- **Session duration**: at least 83.4 s (latest timestamped event in findings)
- **Capture mode**: continuous, no triggered start

---

## Observed traffic (summary from findings)

| Bus                        | Packets | Notes                                      |
|----------------------------|---------|--------------------------------------------|
| R/T (bidirectionalExtensionBoard) | 179 (91 req + 88 resp) | 5-step polling cycle, ~5.5 s period |
| UART wifiBrown (rx)        | 39      | Wi-Fi module -> display                    |
| UART wifiOrange (tx)       | 51      | Display -> Wi-Fi module                    |

### Notable events

| Time (s)   | Channel     | Event                                                         |
|------------|-------------|---------------------------------------------------------------|
| ~0         | R/T         | Polling cycle begins: 0x93 status / 0x41 capability / 0xC0 full status |
| 83.388      | wifiBrown   | Single 0x63 msg_type packet with valid sync byte — unusual, possible wifi pairing/negotiation phase |
| Throughout | R/T         | 5-step polling cycle repeating every ~5.5 s, ~0.198 s per request/response pair |

---

## Open questions from this session

- **Initial AC state**: mode, fan speed, and setpoint were not recorded before capture start.
- **Baud rate of R/T bus**: not directly measured; assumed 9600 bps by analogy with UART.
- **MFB-X HA/HB differential side**: not captured — only the single-ended R/T wire was probed.
- **0x63 packet at 83.4 s**: purpose unknown. Only one instance; may be a wifi dongle negotiation frame specific to startup or pairing.
- **mainboardGrey / mainboardBlue channels**: not yet analysed in findings — direct UART path to mainboard.
