# Session 1 — Follow-Me and program changes

- Date: ~January 2025
- Capture: HVAC-shark ESP dongle, passive XYE sniff via MFB-C adapter
- Controller: KJR-120X wired controller, operated by hand
- Unit state: running (specific mode not recorded)
- Weather: cold, January — around freezing but not deep frost
- Actions: Follow-Me toggling + setpoint/mode changes (details not recorded)
- Quality: some frames lost (unstable bus sniffing)

## Frame summary

- 1,070 frames, ~167 seconds
- C0 Query: 251 cmd + 242 rsp
- C4 Ext.Query: 258 cmd + 254 rsp
- C3 Set: 13 cmd + 9 rsp (some responses lost)
- C6 FollowMe: 12 cmd + 13 rsp
- C3+C6 pairs at: ~39s, 42s, 54s, 56s, 57s, 61s, 63s, 99s, 103s, 106s, 113s, 118s, 124s, 139s
- Some corrupted/partial frames visible near end of capture

## Observations

- C3 mode sweep: Heat -> Fan -> Auto -> Cool -> Dry -> Heat
- C3 fan sweep: Low -> Medium -> High -> Auto (all in Heat mode)
- C3 setpoint: constant 0x51 (=17C with raw-0x40)
- C6 byte[10]: Variant B (0x06=start 9x, 0x04=stop 3x, 0x02=update 1x)
- C6 byte[11]: Follow-Me temp 0x14=20C then 0x15=21C
- C6 byte[6]: first C6 has 0x10 (vertical swing on), rest 0x00
- C0 response modes: Heat, Fan, Dry, Cool, Auto sub-mode 0x91 (heating)
- MASTER_FLAG byte[4] = 0x00 in all 534 commands
- SLAVE_FLAG byte[2] = 0x00 in all 251 responses
