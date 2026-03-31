# HVAC-shark-dumps

This repository contains packet capture dumps from HVAC (Heating, Ventilation, and
Air Conditioning) systems, analysed using the HVAC-shark toolkit.

## Companion repository: HVAC-shark

The tools to capture, convert, and dissect the data in this repository live in the
main project:

**[HVAC-shark](https://github.com/fabcoded/HVAC-shark)**

Contents of HVAC-shark relevant to this repository:
- **Wireshark Lua dissector** (`tools/dissector/`) — load this to decode `.pcap` files from this repo
- **ESP32 / Python live-capture dongle** (`tools/dongle/mid-xye/`) — for live capture over UDP
- **Protocol documentation** (`protocols/`) — spec, devices, comparison, analysis per manufacturer
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

**Brand names and trademarks**: Any manufacturer, product, or model names mentioned
in this repository (including but not limited to "Midea" and associated product
lines) are used solely to identify the hardware under test. Their use is purely
descriptive — to specify which physical device was captured — and does not imply
affiliation, endorsement, or any commercial relationship with the respective
trademark holders. All trademarks remain the property of their respective owners.

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

## External captures

The `external-captures/` directory contains protocol frames sourced from
third-party community posts, forums, and public repositories. **These
subfolders may be licensed differently from the rest of this repository.**
Each subfolder's `capture.yaml` header states the original source, author,
and applicable license. Please review those headers before redistributing
any external-captures content.

## Devices

| Folder                          | Hardware                        |
|---------------------------------|---------------------------------|
| `Midea-XtremeSaveBlue-logicanalyzer` | Midea extremeSaveBlue split A/C — display board (CN1, CN3, IR), logic analyzer |
| `Midea-XtremeSaveBlue-dongle`   | Midea extremeSaveBlue split A/C — MFB-C XYE bus, HVAC-shark ESP dongle |

## Usage

1. Install Wireshark
2. Install the HVAC-shark dissector from the [HVAC-shark repository](https://github.com/fabcoded/HVAC-shark/tree/master/wireshark_dissectors)
3. Open any `.pcap` file from this repository in Wireshark
4. Packets are automatically decoded by the dissector

## Compatibility

These dumps are meant to be used with the latest version of the HVAC-shark Wireshark
dissector. Please ensure you have the latest version installed for proper decoding.

## For AI agents

AI agents working in this repository should follow the instructions in
[AGENTS.md](https://github.com/fabcoded/HVAC-shark/blob/master/AGENTS.md)
in the companion HVAC-shark repository. Unless otherwise advised by the repository
owner, `AGENTS.md` is the authoritative guide for working conventions, protocol
documentation standards, and confidence labelling.
