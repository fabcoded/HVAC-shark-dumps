# AGENTS.md — HVAC-shark-dumps

> Shared conventions (confidence labels, working style, toolchain) are in the
> workspace-level `AGENTS.md` in the parent directory. This file covers
> repo-specific details only.

## Repository purpose

Capture sessions, logic analyser exports, analysis scripts, and the offline
pcap converter. This repo holds data; the tools and dissectors live in
`HVAC-shark/`.

## Directory conventions

Captures are organised by device, then by session: `<Device>/Session N/`

Each session folder contains:


`SessionNotes.md` | Operator log — initial state, sequence of actions (**ground truth** for validating decoded values) 
`findings.md` | Analysis results with confidence labels
| `channels.yaml` | Channel config for the pcap converter |
| `*.csv` | Pre-decoded Logic export (converter input)    |
| `session.pcap` | Converted pcap for Wireshark |

## Analysis scripts

- `logicanalyzer-tools/` — pcap converter and bus decoders (Python)
- `data-analysis/` — validation and cross-bus analysis scripts (Python)

Use `python -X utf8` when running scripts on Windows to avoid encoding
issues with non-ASCII paths.

## Rules

- Do not commit raw `.sal` files (gitignored, too large).
- Do not modify files under `external-captures/` without checking the
  per-subfolder `capture.yaml` for licence constraints.
- When writing `findings.md`, always use the confidence labels defined in the
  workspace-level `AGENTS.md`.
