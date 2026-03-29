# Midea extremeSaveBlue — HVAC-shark dongle captures

## Hardware

- Indoor unit: Midea extremeSaveBlue split AC (second unit, different from display-board captures)
- Adapter board: MFB-C (converts R/T pin to XYE instead of HAHB)
- Wired controller: KJR-120X (operated by hand during captures)
- Capture method: HVAC-shark ESP dongle, passive sniffing XYE bus via RS-485
- Capture date: ~January 2025

## Capture quality

Bus sniffing was somewhat unstable — some frames lost between command/response
pairs (visible as missing C3 responses or orphaned C6 responses). The data is
genuine bus traffic but not gap-free.

## Sessions

| Session | Filename | Frames | Duration | Content |
|---------|----------|--------|----------|---------|
| 1 | session.pcapng | 1,070 | ~167s | Follow-Me + program changes. 13 C3+C6 pairs (setpoint/mode changes via KJR-120X). C0/C4 polling throughout. |
| 2 | session.pcapng | 256 | ~39s | Follow-Me toggle: off-on-off-on pattern. 6 C6 command/response pairs, no C3 set commands. |

## Bus differences from display-board captures

The Midea-XtremeSaveBlue-display sessions captured via logic analyzer on the
display board's CN1 connector (disp-mainboard protocol) and via HAHB RS-485
(XYE frames decoded from digital waveform). This device folder captures
XYE frames directly from the MFB-C adapter board's XYE bus using the
HVAC-shark ESP dongle.
