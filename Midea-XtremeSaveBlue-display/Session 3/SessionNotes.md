# Session 3 — Session Notes (Operator Log)

Ground truth for correlating captured frames to known hardware setup and context.
For analysis results, see findings.md (not yet written).

---

## Hardware under test

- **Unit**: Midea extremeSaveBlue split A/C
- **Capture point**: HAHB RS-485 bus, probed directly at the RS-485 transceiver chip
  on the adapter board; plus the R/T single-wire bus on CN1 (same as Session 1)
- **Logic analyser**: Saleae

---

## Probe setup

| Channel name (CSV)              | Source file              | Capture point                                      | Bus type       |
|---------------------------------|--------------------------|----------------------------------------------------|----------------|
| `bidirectionalExtensionBoard`   | Session 3.csv            | CN1 R/T pin on display board (single-ended)        | r-t_1          |
| `Channel 6`                     | Session 3.hahb.raw.csv   | RS-485 transceiver on adapter board — sum (all traffic) | hahb_raw_chip |
| `Channel 7`                     | Session 3.hahb.raw.csv   | RS-485 transceiver on adapter board — MFB-X → display direction | hahb_raw_chip |

Channel 6 sees all bus traffic (sum of both directions); Channel 7 sees only the
MFB-X → display direction. Channel 6 minus Channel 7 isolates display → MFB-X traffic.

---

## Hardware observations — MFB-X adapter board

The adapter board in this session is an **MFB-X**.  Compared to the **MFB-C**
(the standard XYE RS-485 adapter):

- **Connector terminals**: the MFB-X has **2 wire connections** instead of 4.
  The MFB-C uses 4 terminals (HA, HB, 12 V, GND); the MFB-X only exposes the
  two differential signal wires (HA, HB) — no 12 V or GND terminals.
  The terminal block for the 2 wires is at a slightly different position on the
  PCB compared to the MFB-C.

- **Magnetic / signal transformer**: the MFB-X carries a small
  magnetic/transformer component that is absent on the MFB-C.  This transformer
  appears to AC-couple the differential bus signal and filter the DC path,
  isolating the signal from any DC bias on the HA/HB lines.  The same type of
  transformer is present on the KJR-120M/BGEF room controller used in this
  session (and in Session 1).

- **Protocol**: despite the hardware differences, the bus traffic decoded as
  standard XYE frames (same command codes, same frame structure).  The MFB-X
  appears to be a variant of the MFB-C intended for installations where 12 V
  power over the bus cable is not available or not wanted.

---

## Room controller

Same **KJR-120M/BGEF** wired wall controller as used in Session 1, connected
to the HA/HB side of the MFB-X adapter.

---

## Session context

- **AC state at session start**: not logged
- **Operator actions during session**: none (passive observation)
- **Capture mode**: continuous, no triggered start

---

## Open questions from this session

- **MFB-X vs MFB-C pinout**: confirm whether HA/HB on MFB-X are electrically
  equivalent to HA/HB on MFB-C, or whether the transformer changes the polarity
  or impedance.
- **HAHB baud rate**: confirmed 48 000 baud by the decoder; cross-check against
  physical measurement not yet performed.
