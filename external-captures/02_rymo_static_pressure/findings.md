# Findings: 02_rymo_static_pressure

Source: rymo via HA Community
Hardware: Unknown Midea ducted unit with static pressure control (SP0..SP4)
Capture method: Monitoring wall controller XYE commands

## Data quality

- 10 frames in 1 session (5 command/response pairs)
- CRC validation: 10/10 frames pass
- Very clean dataset: only byte[24] and CRC vary across all 5 responses

## Analysis results

### Transferred to protocol spec (candidate)

**C6 byte[8] — Static Pressure via C6 Mode Flags** (5 pairs, all CRC-valid)
- C6 command byte[8] = 0x1N sets static pressure level N (SP0=0x10 .. SP4=0x14)
- Upper nibble 0x1 = static pressure command, lower nibble = level 0-4
- Own captures: byte[8] constant 0x00 across 107 C6 commands (no SP feature on test unit)
- Status: single-source candidate in protocol_xye.md and dissector

**C6 response byte[24] — Static Pressure Readback** (5 responses)
- Response byte[24] = 0x2N echoes static pressure level N (SP0=0x20 .. SP4=0x24)
- Upper nibble 0x2 = SP readback, lower nibble matches command
- Own captures: byte[24] constant 0x00 across 107 C6 responses (no SP feature)
- Status: single-source candidate in protocol_xye.md and dissector

**C6 byte[10] — Sub-command type** (5 frames, cross-referenced with ESPHome + mdrobnak)
- All rymo C6 commands use byte[10]=0x04 (Variant B, bit 0x40 clear)
- Matches mdrobnak pattern: 0x02 (update) / 0x04 (stop/config) / 0x06 (start)
- Own captures use Variant A (bit 0x40 set): 0x42/0x44/0x46 — same lower nibbles
- ESPHome esphome-mideaXYE-rs485 confirms Variant A: 0x46=start, 0x42=update, 0x44=stop
- Bit 0x40 difference: ESP-based masters set it, KJR-120X/wall controllers do not
- Status: transferred to protocol_xye.md as documented variant with 3 independent sources

### Observations not transferred

**C6 byte[11] = 0x17 (23 decimal)**
- Constant across all 5 SP commands, purpose unclear
- rymo suggests possibly temperature-related (23C?)
- Single value, no variation to analyze

**C6 response byte[10] = 0x1C (ext_caps_2)**
- Different from mdrobnak (0x98) and varies across hardware
- Likely a unit capability bitmask, hardware-variant dependent

**C6 response byte[15] = 0x00 (EXT_STATUS)**
- Matches our own captures (0x00)
- Differs from mdrobnak (0x20 baseline)
- Hardware-variant dependent

**C6 response byte[19] = 0xBE (DEVICE_TYPE)**
- Our HW: 0xBC, rymo: 0xBE — likely identifies outdoor unit model variant
