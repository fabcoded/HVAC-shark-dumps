# Findings: 01_mdrobnak_ch36ahu

Source: mdrobnak (Matthew Drobnak) via HA Community
Hardware: Cooper & Hunter CH-36AHU (36K BTU ducted heat pump, Midea OEM)
Controller: KJR-120X wired controller
Capture method: ESP32 + TTL-RS485 adapter, ESPHome UART debug (passive sniff)

## Data quality

- 39 frames across 8 sessions
- CRC validation: 14/15 checked frames pass, 1 off-by-1 (Session 2 C4 response — likely transcription error)
- Hand-transcribed from ESPHome UART debug logs, not raw bus capture

## Analysis results

### Transferred to protocol spec (candidate)

**Emergency Heat via C6/C4** (Session 4, 4 cross-checks, internally consistent)
- C6 command byte[8] = 0x80 activates emergency (aux-only) heat
- C4 response byte[15] bit 0x40 confirms emergency heat active
- Non-emergency: 3x C6 byte[8]=0x00 with C4 byte[15]=0x20 (0x40 clear)
- Emergency: 1x C6 byte[8]=0x80 with C4 byte[15]=0x60 (0x40 set)
- All frames CRC-valid
- Status: single-source candidate in protocol_xye.md and dissector

### Confirmed by own captures (transferred to spec)

**DIR_FLAG = 0x00 for both directions**
- All mdrobnak frames have byte[2]=0x00 regardless of direction
- **Confirmed**: our own logic analyzer captures also show 0x00 in ALL 4,847 XYE frames (Sessions 3-9)
- Codeberg spec claim of 0x80 for slave->master is wrong — corrected in protocol_xye.md
- Dissector labels updated from "From Master"/"To Master" to "Master Flag"/"Slave Flag"

### Observations not transferred (insufficient evidence)

**C0 setpoint encoding: direct value (no offset)**
- byte[10] = 0x15 for 21C, 0x18 for 24C — raw = degrees
- Our HW uses raw - 0x40 = degrees
- Contradicts our spec — needs second source

**C3 setpoint Celsius/Fahrenheit split at 0x80**
- Values < 0x80 increment in 1C steps (0x56, 0x57, 0x58)
- Values >= 0x80 are Fahrenheit range (0xCB, 0xCF)
- Only 4 command frames, no responses to cross-check

**Bytes 28-29 startup status counter** (Session 6)
- Power-on sequence: 0x00:0x00 -> 0x03:0x00 -> 0x03:0x01 -> 0x05:0x02 -> 0x12:0x00 -> 0xE0:0x01
- Byte[27] = 0x14 constant (our HW: 0xFF)
- 7 frames showing clear progression, but single hardware instance

**C4 off-mode byte[16] = 0x04**
- Off state represented as 0x04, not 0x00
- Single frame observation

**Fan byte[9] encoding**
- Session 7 claims 0x80 = auto flag in upper bit, lower nibble = speed
- All 3 frames show byte[9]=0x80 (auto, speed 0) — no variation in actual speed values captured
- Description mentions 0x84/0x82/0x81 but these values are not present in the captured frames
