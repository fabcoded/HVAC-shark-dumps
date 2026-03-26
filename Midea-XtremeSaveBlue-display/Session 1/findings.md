# Session 1 — Findings

## Session context

First capture session on the Midea XtremeSaveBlue display board.
Key discovery: the **R/T extension board bus (CN1) carries UART-compatible commands**
over HA/HB framing. The body command set (`0xC0`, `0xC1`, `0x41`, `0x93`) is identical
to the Midea UART protocol, establishing the link between the R/T pin and the UART
protocol on this hardware platform.

---

## UART Sync Byte (byte[3]) is always 0x00

The PI HVAC databridge protocol spec defines byte[3] of the UART frame as a
"sync byte", calculated as `LENGTH XOR APPLIANCE_TYPE` (byte[1] XOR byte[2]).

In this capture, **89 out of 90 UART packets have sync = 0x00** — the device
firmware does not implement the XOR formula. The sync field is simply left
uninitialized / zeroed out.

- Affected channels: `wifiBrown` (rx), `wifiOrange` (tx)
- Total UART packets: 90
- Sync == 0x00: 89 (98.9%)
- Sync != 0x00: 1

### Breakdown by channel and message type

**wifiBrown** (rx — wifi module to display, 39 packets):

| msg_type | sync=0x00 | sync valid |
|---|---|---|
| 0x02 | 4 | — |
| 0x03 | 27 | — |
| 0x05 | 5 | — |
| 0x63 | — | 1 |
| 0xA0 | 2 | — |

**wifiOrange** (tx — display to wifi module, 51 packets):

| msg_type | sync=0x00 | sync valid |
|---|---|---|
| 0x02 | 4 | — |
| 0x03 | 27 | — |
| 0x04 | 12 | — |
| 0x05 | 5 | — |
| 0x63 | 1 | — |
| 0xA0 | 2 | — |

Note: msg_type 0x63 appears on both channels but only the `wifiBrown` instance
has a valid sync byte. The 0x63 on `wifiOrange` has sync=0x00 like everything
else — so the valid sync may be specific to the wifi module's firmware (rx
direction), not the display board (tx direction).

### The one exception

A single packet on `wifiBrown` does carry a valid sync byte:

| Field | Value |
|---|---|
| Channel | wifiBrown |
| Start time | 83.387996 s |
| Sync byte | 0xB2 (matches LENGTH 0x1E XOR APPLIANCE 0xAC = 0xB2) |
| Message type | 0x63 (unusual — not a standard 0x03/0x02/0x04 msg type) |
| Frame length | 0x1E (30 bytes + start = 31 total) |
| Raw bytes | `AA 1E AC B2 00 00 00 00 02 63 01 01 04 04 B3 A8 C0 FF 00 00 00 00 01 00 00 00 03 00 00 00 F7` |

This packet also has an unusual message type (0x63) compared to the rest of the
session traffic (0x02, 0x03, 0x04), suggesting it may originate from different
firmware or a different communication phase (e.g. pairing/negotiation with the
wifi module).

### Conclusion

The sync byte validation in the spec is not reliable for this device
(Midea XtremeSaveBlue, display board wifi interface). Dissectors should treat
`sync == 0x00` as "not implemented" rather than an error.


## R/T Extension Board Bus (bidirectionalExtensionBoard)

### Physical layer and pin identity

The R/T pin is a **single-wire bidirectional half-duplex bus** on connector CN1 of
the display board. "R/T" stands for Receive/Transmit — both directions share the
same physical wire, multiplexed by direction (start byte distinguishes them).

The wire runs from the display board to a converter PCB which bridges it onto the
HA/HB differential bus toward the mainboard. The capture in this session probes
the single-ended side (before the converter), identified in `channels.yaml` as
channel `bidirectionalExtensionBoard`, busType `r-t_1`.

CN1 also carries two separate unidirectional wires to the mainboard (grey = rxd,
blue = txd, busType `disp-mainboard_1`), which are a different, direct UART path
and not part of the R/T bus.

Baud rate of the R/T bus: **[UNKNOWN — not measured in this session]**.
The framing and timing are consistent with 9600 bps (same as the Wi-Fi UART port)
but this has not been confirmed with a direct measurement.

The CN1 extension board uses a bidirectional half-duplex bus. The data on this
wire is converted to the HA/HB bus by a converter PCB, so the framing reflects
the HA/HB bus protocol rather than direct UART. 179 packets total (91 requests,
88 responses).

### Frame structure

| Byte | Field | Values |
|---|---|---|
| 0 | Start | `0xAA` (request from display) / `0x55` (response from ext. board) |
| 1 | Device Type | `0xBC` (constant — extension board) |
| 2 | Length | data length; **total packet = byte[2] + 4** |
| 3 | Appliance Type | `0xAC` (air conditioner) |
| 4..8 | Reserved | `00 00 00 00 00` (5 bytes) |
| 9 | Protocol Version | `0x03` |
| 10 | Message Type | `0x03` (data) or `0x02` (ack) |
| 11..N-5 | Body | UART-compatible command payload |
| N-4 | CRC-8 | CRC-8/854 over body bytes [11..N-5] (confirmed 90/90 for 0xAA) |
| N-3 | Checksum | XYE-style additive checksum (see Integrity section) |
| N-2 | Padding | `0x00` (always) |
| N-1 | Frame integrity | see below |

**Comparison with UART:**

|  | UART | R/T (HA/HB) bus |
|---|---|---|
| byte[0] | `0xAA` (always) | `0xAA` / `0x55` (direction) |
| byte[1] | LENGTH | Device Type (`0xBC`) |
| byte[2] | Appliance Type (`0xAC`) | LENGTH |
| byte[3] | Sync (len XOR appl) | Appliance Type (`0xAC`) |
| byte[4..7] | Reserved (4 bytes) | Reserved (5 bytes, byte[4..8]) |
| byte[8] / byte[9] | Protocol Version | Protocol Version |
| byte[9] / byte[10] | Message Type | Message Type |
| Body start | byte[10] | byte[11] |
| Length formula | total = byte[1] + 1 | total = byte[2] + 4 |

The header is shifted by 1 byte compared to UART: device type `0xBC` is
inserted at byte[1], pushing length to byte[2] and adding one extra reserved
byte. The body commands are identical to UART.

### Packet lengths

- `0xAA` requests: always 38 bytes (byte[2]=0x22), except one 5-byte truncated packet
- `0x55` responses: 38 bytes (byte[2]=0x22) or 44 bytes (byte[2]=0x28)
- **byte[2] + 4 == actual packet length** holds for 178/179 packets (99.4%)

### Integrity / checksum

**Both directions:** sum of all bytes in the packet equals `0x00` mod 256.

Three integrity layers, analogous to UART (CRC-8 + additive checksum):

**0xAA request packets:**
- byte[N-4]: CRC-8/854 over body bytes [11..N-5] — **confirmed 90/90**
- byte[N-3]: XYE-style additive checksum (two's complement of sum) over
  bytes [1..N-4] — **confirmed 90/90**
- byte[N-2]: `0x00` (padding)
- byte[N-1]: frame checksum (two's complement, makes full packet sum = 0)

**0x55 response packets:**
- byte[N-3]: XYE-style additive checksum (two's complement of sum) over
  bytes [2..N-3] — **confirmed 88/88**
- byte[N-2]: `0x00` (padding)
- byte[N-1]: `0xEF` (fixed end-of-frame marker)
- Note: the checksum range differs between directions — 0xAA uses [1..N-4],
  0x55 uses [2..N-3]. The frame still sums to 0 mod 256 in both cases.

### Timing

Request/response pairs are spaced ~0.198s apart. The full polling cycle
repeats every ~5.5s (5 request/response pairs per cycle).

### Polling cycle

The display polls the extension board in a strict 5-step repeating cycle.
The body command IDs match the UART protocol:

| Step | Req cmd | Req params | Resp cmd | Resp len | Description |
|---|---|---|---|---|---|
| 1 | 0x93 | 00 80 84 | 0x93 | 44 | Status query/response |
| 2 | 0x41 | 81 01 41 | 0xC1 | 38 | Capability query page 0x41 |
| 3 | 0x41 | 81 01 42 | 0xC1 | 38 | Capability query page 0x42 |
| 4 | 0x41 | 81 01 43 | 0xC1 | 38 | Capability query page 0x43 |
| 5 | 0x41 | 81 00 FF | 0xC0 | 44 | Full status response |

### Key observation

The body command IDs (`0xC0`, `0xC1`, `0x41`, `0x93`) are **identical to the
UART protocol's command set**. This bus transports UART-compatible commands
over HA/HB framing. The UART body decoders (C0 status, C1 power, 0x41 query)
can be reused by adjusting the body offset from byte[10] (UART) to byte[11]
(R/T bus).

### The 5-byte truncated packet

One packet is only 5 bytes: `AA BC 22 AC 00`. This is just the header with no
payload — likely a startup probe or bus reset artifact.
