# HVAC-shark-dumps

This repository contains packet capture dumps from HVAC (Heating, Ventilation, and
Air Conditioning) systems, analysed using the HVAC-shark toolkit.

## Companion repository: HVAC-shark

The tools to capture, convert, and dissect the data in this repository live in the
main project:

**[HVAC-shark](https://github.com/fabianschwamborn/HVAC-shark)**

Contents of HVAC-shark relevant to this repository:
- **Wireshark Lua dissector** (`wireshark_dissectors/`) — load this to decode `.pcap` files from this repo
- **ESP32 / Python live-capture dongle** (`dongle/mid-xye/`) — for live capture over UDP
- **Protocol reference documents** (`protocol-analysis/`) — field-level documentation for all captured buses
- **`AGENTS.md`** — instructions for AI agents working across both repositories

The offline pcap converter that processes the raw Saleae exports in this repository:

```
logicanalyzer-tools/saleae_midea_recording_to_pcap.py
```

## Disclaimer

Please note that the data provided in this repository may contain errors, malformed
entries, or lack proper annotations. Users should not rely solely on this data for
critical applications. Always validate and verify the information before using it
in your projects.

## Repository structure

Captures are organised by device, then by session:

```
<Device>/
  README.md              Device overview, bus list, session index
  Session N/
    SessionNotes.md      Operator log — initial state, sequence of actions
    findings.md          Analysis output — field encodings, confidence levels, open questions
    channels.yaml        Channel config for the pcap converter
    Session N.csv        Pre-decoded Saleae Logic export (converter input)
    session.pcap         Converted pcap, open directly in Wireshark
```

## Devices

| Folder                          | Hardware                        |
|---------------------------------|---------------------------------|
| `Midea-extremeSaveBlue-display` | Midea extremeSaveBlue split A/C — display board (CN1, CN3, IR) |

## Usage

1. Install Wireshark
2. Install the HVAC-shark dissector from the [HVAC-shark repository](https://github.com/fabianschwamborn/HVAC-shark/tree/master/wireshark_dissectors)
3. Open any `.pcap` file from this repository in Wireshark
4. Packets are automatically decoded by the dissector

## Compatibility

These dumps are meant to be used with the latest version of the HVAC-shark Wireshark
dissector. Please ensure you have the latest version installed for proper decoding.

## For AI agents

AI agents working in this repository should follow the instructions in
[AGENTS.md](https://github.com/fabianschwamborn/HVAC-shark/blob/master/AGENTS.md)
in the companion HVAC-shark repository. Unless otherwise advised by the repository
owner, `AGENTS.md` is the authoritative guide for working conventions, protocol
documentation standards, and confidence labelling.
