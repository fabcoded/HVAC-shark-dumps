#!/usr/bin/env python3
"""
XYE/HAHB Frame Survey — extract and tabulate XYE frame data from HVAC-shark pcap sessions.

Runs tshark on each session, parses Raw Frame hex from verbose output,
and produces summary tables of command types, C0/C4 payloads, and D0 broadcasts.

Includes external captures (mdrobnak, rymo) and filters by CRC validity.
"""

import subprocess
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

TSHARK = "C:/Program Files/Wireshark/tshark.exe"
BASE_LA = Path("C:/Users/fabia/OneDrive/Elektronik und Basteln/HVAC and Heat/HVAC Shark DEV/HVAC-shark-dumps/Midea-XtremeSaveBlue-logicanalyzer")
BASE_DONGLE = Path("C:/Users/fabia/OneDrive/Elektronik und Basteln/HVAC and Heat/HVAC Shark DEV/HVAC-shark-dumps/Midea-XtremeSaveBlue-dongle")
BASE_EXT = Path("C:/Users/fabia/OneDrive/Elektronik und Basteln/HVAC and Heat/HVAC Shark DEV/HVAC-shark-dumps/external-captures")
OUTPUT = Path("C:/Users/fabia/OneDrive/Elektronik und Basteln/HVAC and Heat/HVAC Shark DEV/HVAC-shark-dumps/data-analysis/midea/xye_frame_survey.txt")

# Command code names
CMD_NAMES = {
    0xC0: "C0 Query",
    0xC3: "C3 Write",
    0xC4: "C4 Ext.Query",
    0xC6: "C6 Ext.Write",
    0xCC: "CC Lock",
    0xCD: "CD Unlock",
    0xD0: "D0 Broadcast",
}

# Build session list: (label, pcap_path, display_filter)
# display_filter=None means no tshark filter (external captures are raw XYE)
sessions = []
# Logic analyzer sessions 1-13
for n in range(1, 14):
    p = BASE_LA / f"Session {n}" / "session.pcap"
    sessions.append((f"LA-S{n:02d}", p, "hvac_shark.bus_type == 0"))
# Dongle sessions
for n in range(1, 3):
    p = BASE_DONGLE / f"Session {n}" / "session.pcapng"
    sessions.append((f"Dongle-S{n}", p, "hvac_shark.bus_type == 0"))
# External captures — mdrobnak (multiple session pcaps)
for n in range(1, 9):
    p = BASE_EXT / "01_mdrobnak_ch36ahu" / f"session_{n:02d}.pcap"
    sessions.append((f"mdrobnak-S{n:02d}", p, "hvac_shark"))
# External captures — rymo (single session pcap)
p = BASE_EXT / "02_rymo_static_pressure" / "session_01.pcap"
sessions.append(("rymo-S01", p, "hvac_shark"))


def run_tshark(pcap_path, display_filter="hvac_shark.bus_type == 0"):
    """Run tshark -V on a pcap with the given filter, return stdout lines."""
    cmd = [TSHARK, "-r", str(pcap_path)]
    if display_filter:
        cmd += ["-Y", display_filter]
    cmd += ["-V"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.stdout.splitlines()
    except FileNotFoundError:
        print(f"  ERROR: tshark not found at {TSHARK}", file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT on {pcap_path}", file=sys.stderr)
        return []


def verify_crc(byt):
    """Verify XYE frame CRC. Returns True if CRC is valid.

    CRC = (-sum(bytes[1..N-2])) & 0xFF, stored at byte[N-2].
    N = len(byt) (16 for commands, 32 for responses/broadcasts).
    """
    if len(byt) < 4:
        return False
    n = len(byt)
    crc_pos = n - 2  # byte[14] for 16B, byte[30] for 32B
    inner_sum = sum(byt[1:crc_pos]) & 0xFF
    expected_crc = (-inner_sum) & 0xFF
    return byt[crc_pos] == expected_crc


def parse_raw_frames(lines):
    """Extract Raw Frame hex strings from tshark -V output."""
    frames = []
    for line in lines:
        m = re.match(r'\s+Raw Frame:\s+([0-9A-Fa-f]+)', line)
        if m:
            frames.append(m.group(1).upper())
    return frames


def parse_frame(hex_str):
    """Parse an XYE frame hex string into a dict. Returns None if not a valid XYE frame."""
    byt = bytes.fromhex(hex_str)
    if len(byt) < 2:
        return None
    # Only accept valid XYE command codes
    if byt[1] not in (0xC0, 0xC3, 0xC4, 0xC6, 0xCC, 0xCD, 0xD0):
        return None
    # Only accept expected frame sizes (16 or 32)
    if len(byt) not in (16, 32):
        return None
    crc_ok = verify_crc(byt)
    return {
        "raw": hex_str,
        "length": len(byt),
        "preamble": byt[0],
        "cmd": byt[1],
        "dest": byt[2] if len(byt) > 2 else None,
        "src_id": byt[3] if len(byt) > 3 else None,
        "master_flag": byt[4] if len(byt) > 4 else None,
        "own_id": byt[5] if len(byt) > 5 else None,
        "payload_6_12": hex_str[12:26] if len(byt) >= 13 else None,  # bytes 6..12 = chars 12..26
        "bytes": byt,
        "crc_ok": crc_ok,
    }


def main():
    # Per-session data
    session_cmd_counts = {}  # label -> Counter of cmd codes
    session_frame_counts = {}  # label -> total frame count

    # Global collectors
    all_c0_commands = []  # list of parsed frames (16-byte C0)
    all_c4_commands = []  # list of parsed frames (16-byte C4)
    all_d0_frames = []    # list of parsed frames (D0, any length)
    all_frames = []       # all parsed frames

    crc_fail_total = 0

    for label, pcap_path, display_filter in sessions:
        if not pcap_path.exists():
            print(f"[{label}] SKIP — file not found: {pcap_path}")
            session_cmd_counts[label] = Counter()
            session_frame_counts[label] = 0
            continue

        print(f"[{label}] Processing {pcap_path.name} ...")
        lines = run_tshark(pcap_path, display_filter)
        raw_frames = parse_raw_frames(lines)

        cmd_counter = Counter()
        crc_fail = 0
        accepted = 0
        for hex_str in raw_frames:
            f = parse_frame(hex_str)
            if f is None:
                continue
            if not f["crc_ok"]:
                crc_fail += 1
                continue
            f["session"] = label
            all_frames.append(f)
            cmd_counter[f["cmd"]] += 1
            accepted += 1

            # Collect 16-byte command frames for C0 and C4
            if f["length"] == 16 and f["cmd"] == 0xC0:
                all_c0_commands.append(f)
            if f["length"] == 16 and f["cmd"] == 0xC4:
                all_c4_commands.append(f)
            if f["cmd"] == 0xD0:
                all_d0_frames.append(f)

        crc_fail_total += crc_fail
        fail_note = f" ({crc_fail} CRC fail rejected)" if crc_fail else ""
        print(f"  Found {len(raw_frames)} raw, {accepted} CRC-valid XYE frames{fail_note}")

        session_cmd_counts[label] = cmd_counter
        session_frame_counts[label] = accepted

    # ── Build output ──
    out = []
    out.append("=" * 100)
    out.append("XYE Frame Survey — Midea XtremeSave Blue")
    out.append("  CRC-validated only. Includes external captures (mdrobnak, rymo).")
    out.append(f"  CRC failures rejected: {crc_fail_total}")
    out.append("=" * 100)
    out.append("")

    # ── 1. Frame counts per command per session ──
    all_cmds = sorted(set(c for cc in session_cmd_counts.values() for c in cc))
    cmd_labels = [f"0x{c:02X}" for c in all_cmds]

    out.append("─" * 100)
    out.append("1. FRAME COUNTS PER COMMAND TYPE PER SESSION")
    out.append("─" * 100)

    # Header
    hdr = f"{'Session':<14}" + "".join(f"{cl:>10}" for cl in cmd_labels) + f"{'TOTAL':>10}"
    out.append(hdr)
    out.append("-" * len(hdr))

    totals_per_cmd = Counter()
    grand_total = 0
    for label, _, _ in sessions:
        cc = session_cmd_counts.get(label, Counter())
        total = session_frame_counts.get(label, 0)
        if total == 0 and not any(cc.values()):
            continue
        row = f"{label:<14}"
        for c in all_cmds:
            row += f"{cc.get(c, 0):>10}"
            totals_per_cmd[c] += cc.get(c, 0)
        row += f"{total:>10}"
        grand_total += total
        out.append(row)

    out.append("-" * len(hdr))
    row = f"{'TOTAL':<14}"
    for c in all_cmds:
        row += f"{totals_per_cmd[c]:>10}"
    row += f"{grand_total:>10}"
    out.append(row)
    out.append("")

    # ── 1b. Frame size distribution per command ──
    out.append("─" * 100)
    out.append("1b. FRAME SIZE DISTRIBUTION PER COMMAND TYPE")
    out.append("─" * 100)
    size_by_cmd = defaultdict(Counter)
    for f in all_frames:
        size_by_cmd[f["cmd"]][f["length"]] += 1
    for cmd in sorted(size_by_cmd):
        name = CMD_NAMES.get(cmd, f"0x{cmd:02X}")
        sizes = size_by_cmd[cmd]
        parts = ", ".join(f"{sz}B: {cnt}" for sz, cnt in sorted(sizes.items()))
        out.append(f"  0x{cmd:02X} ({name:>14}): {parts}")
    out.append("")

    # ── 2. Unique C0 command payloads (16-byte frames) ──
    out.append("─" * 100)
    out.append("2. UNIQUE C0 QUERY COMMAND PAYLOADS (16-byte frames, bytes 6-12)")
    out.append("─" * 100)

    c0_payload_counter = Counter()
    c0_payload_sessions = defaultdict(set)
    c0_payload_full = defaultdict(set)
    for f in all_c0_commands:
        pl = f["payload_6_12"]
        c0_payload_counter[pl] += 1
        c0_payload_sessions[pl].add(f["session"])
        c0_payload_full[pl].add(f["raw"])

    out.append(f"{'Payload (B6-12)':<18} {'Count':>7}  {'Sessions':<40}  Full Frame Example")
    out.append("-" * 100)
    for pl, cnt in c0_payload_counter.most_common():
        sess = ", ".join(sorted(c0_payload_sessions[pl]))
        example = sorted(c0_payload_full[pl])[0]
        out.append(f"{pl:<18} {cnt:>7}  {sess:<40}  {example}")
    out.append(f"\nTotal C0 command frames: {len(all_c0_commands)}, unique payloads: {len(c0_payload_counter)}")
    out.append("")

    # ── 3. Unique C4 command payloads (16-byte frames) ──
    out.append("─" * 100)
    out.append("3. UNIQUE C4 EXT.QUERY COMMAND PAYLOADS (16-byte frames, bytes 6-12)")
    out.append("─" * 100)

    c4_payload_counter = Counter()
    c4_payload_sessions = defaultdict(set)
    c4_payload_full = defaultdict(set)
    for f in all_c4_commands:
        pl = f["payload_6_12"]
        c4_payload_counter[pl] += 1
        c4_payload_sessions[pl].add(f["session"])
        c4_payload_full[pl].add(f["raw"])

    out.append(f"{'Payload (B6-12)':<18} {'Count':>7}  {'Sessions':<40}  Full Frame Example")
    out.append("-" * 100)
    for pl, cnt in c4_payload_counter.most_common():
        sess = ", ".join(sorted(c4_payload_sessions[pl]))
        example = sorted(c4_payload_full[pl])[0]
        out.append(f"{pl:<18} {cnt:>7}  {sess:<40}  {example}")
    out.append(f"\nTotal C4 command frames: {len(all_c4_commands)}, unique payloads: {len(c4_payload_counter)}")
    out.append("")

    # ── 4. D0 broadcast byte distributions ──
    out.append("─" * 100)
    out.append("4. D0 BROADCAST ANALYSIS")
    out.append("─" * 100)

    if all_d0_frames:
        # Group by frame length
        d0_by_len = defaultdict(list)
        for f in all_d0_frames:
            d0_by_len[f["length"]].append(f)

        for flen in sorted(d0_by_len):
            frames = d0_by_len[flen]
            out.append(f"\n  D0 frames of length {flen} bytes: {len(frames)} total")

            # Show unique full frames
            unique_raw = Counter(f["raw"] for f in frames)
            out.append(f"  Unique frames: {len(unique_raw)}")
            out.append(f"  {'Full Hex':<72} {'Count':>7}")
            out.append("  " + "-" * 82)
            for raw, cnt in unique_raw.most_common(50):
                out.append(f"  {raw:<72} {cnt:>7}")

            # Byte-level distribution for each position
            if flen > 6:
                out.append(f"\n  Per-byte value distribution (bytes 6 to {flen-4}) for {flen}B D0 frames:")
                for pos in range(6, flen - 3):  # skip preamble/cmd/addr/crc/eof
                    vals = Counter(f["bytes"][pos] for f in frames if len(f["bytes"]) > pos)
                    top = vals.most_common(10)
                    desc = ", ".join(f"0x{v:02X}:{c}" for v, c in top)
                    out.append(f"    Byte[{pos:2d}]: {desc}")
    else:
        out.append("  No D0 frames found.")
    out.append("")

    # ── 5. Raw hex dump of all unique C0 and C4 16-byte command frames ──
    out.append("─" * 100)
    out.append("5. COMPLETE RAW HEX DUMP — ALL UNIQUE C0 COMMAND FRAMES (16B)")
    out.append("─" * 100)
    c0_unique = Counter(f["raw"] for f in all_c0_commands)
    out.append(f"{'#':>5}  {'Raw Hex (16 bytes)':<36}  B0   B1   B2   B3   B4   B5   B6   B7   B8   B9   B10  B11  B12  B13  B14  B15")
    out.append("-" * 120)
    for raw, cnt in c0_unique.most_common():
        byt = bytes.fromhex(raw)
        byte_cols = "  ".join(f"{b:02X}" for b in byt[:16])
        out.append(f"{cnt:>5}  {raw:<36}  {byte_cols}")
    out.append("")

    out.append("─" * 100)
    out.append("6. COMPLETE RAW HEX DUMP — ALL UNIQUE C4 COMMAND FRAMES (16B)")
    out.append("─" * 100)
    c4_unique = Counter(f["raw"] for f in all_c4_commands)
    out.append(f"{'#':>5}  {'Raw Hex (16 bytes)':<36}  B0   B1   B2   B3   B4   B5   B6   B7   B8   B9   B10  B11  B12  B13  B14  B15")
    out.append("-" * 120)
    for raw, cnt in c4_unique.most_common():
        byt = bytes.fromhex(raw)
        byte_cols = "  ".join(f"{b:02X}" for b in byt[:16])
        out.append(f"{cnt:>5}  {raw:<36}  {byte_cols}")
    out.append("")

    # ── 7. C0/C4 response frames (32-byte) — unique payloads ──
    out.append("─" * 100)
    out.append("7. C0 RESPONSE FRAMES (32-byte) — UNIQUE RAW FRAMES")
    out.append("─" * 100)
    c0_responses = [f for f in all_frames if f["cmd"] == 0xC0 and f["length"] == 32]
    c0r_unique = Counter(f["raw"] for f in c0_responses)
    out.append(f"Total: {len(c0_responses)}, Unique: {len(c0r_unique)}")
    for raw, cnt in c0r_unique.most_common(30):
        out.append(f"  {cnt:>5}x  {raw}")
    out.append("")

    out.append("─" * 100)
    out.append("8. C4 RESPONSE FRAMES (32-byte) — UNIQUE RAW FRAMES")
    out.append("─" * 100)
    c4_responses = [f for f in all_frames if f["cmd"] == 0xC4 and f["length"] == 32]
    c4r_unique = Counter(f["raw"] for f in c4_responses)
    out.append(f"Total: {len(c4_responses)}, Unique: {len(c4r_unique)}")
    for raw, cnt in c4r_unique.most_common(30):
        out.append(f"  {cnt:>5}x  {raw}")
    out.append("")

    # ── 9. Per-byte distributions for 32-byte response frames (C0, C3, C4, C6) ──
    for resp_cmd, resp_name in [(0xC0, "C0"), (0xC3, "C3"), (0xC4, "C4"), (0xC6, "C6")]:
        resp_frames = [f for f in all_frames if f["cmd"] == resp_cmd and f["length"] == 32]
        if not resp_frames:
            continue
        out.append("─" * 100)
        out.append(f"9{resp_name}. {resp_name} RESPONSE (32B) — PER-BYTE VALUE DISTRIBUTION (CRC-valid only)")
        out.append("─" * 100)
        out.append(f"  Total {resp_name} responses: {len(resp_frames)}")
        # List which sessions contributed
        resp_sessions = sorted(set(f["session"] for f in resp_frames))
        out.append(f"  Sessions: {', '.join(resp_sessions)}")
        out.append("")
        for pos in range(32):
            vals = Counter(f["bytes"][pos] for f in resp_frames if len(f["bytes"]) > pos)
            n_distinct = len(vals)
            total = sum(vals.values())
            if n_distinct == 1:
                v, c = vals.most_common(1)[0]
                out.append(f"    Byte[{pos:2d}]: 0x{v:02X} constant ({c}/{total})")
            elif n_distinct <= 15:
                desc = ", ".join(f"0x{v:02X}:{c}" for v, c in vals.most_common())
                out.append(f"    Byte[{pos:2d}]: [{n_distinct} values] {desc}")
            else:
                top = vals.most_common(10)
                desc = ", ".join(f"0x{v:02X}:{c}" for v, c in top)
                out.append(f"    Byte[{pos:2d}]: [{n_distinct} values] {desc} ...")
        out.append("")

    # Write output
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"\nOutput written to: {OUTPUT}")
    print(f"Grand total: {grand_total} CRC-valid XYE frames across {sum(1 for l,_,_ in sessions if session_frame_counts.get(l,0) > 0)} sessions")
    if crc_fail_total:
        print(f"CRC failures rejected: {crc_fail_total}")


if __name__ == "__main__":
    main()
