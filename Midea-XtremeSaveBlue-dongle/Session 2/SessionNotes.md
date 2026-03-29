# Session 2 — Follow-Me off/on toggle

- Date: ~January 2025
- Capture: HVAC-shark ESP dongle, passive XYE sniff via MFB-C adapter
- Controller: KJR-120X wired controller, operated by hand
- Unit state: running (specific mode not recorded)
- Weather: cold, January — around freezing but not deep frost
- Actions: Follow-Me toggled off-on-off-on repeatedly
- Quality: some frames lost (unstable bus sniffing)

## Frame summary

- 256 frames, ~39 seconds
- C0 Query: 61 cmd + 62 rsp
- C4 Ext.Query: 60 cmd + 61 rsp
- C6 FollowMe: 6 cmd + 6 rsp (no C3 Set commands — pure C6 toggle)
- C6 pairs at: ~11.7s, 14.8s, 20.1s, 24.1s, 28.4s, 33.7s
- Spacing: ~4-5 seconds between Follow-Me toggles

## Observations

- C6 byte[10] alternates: 0x06 (start) / 0x04 (stop) / 0x06 / 0x04 / 0x06 / 0x04
- Clean on-off-on-off-on-off pattern — Variant B confirmed
- C6 byte[11]: Follow-Me temp 0x13=19C, last frame 0x14=20C
- No C3 commands — Follow-Me toggle does not require C3 in this session
- MASTER_FLAG byte[4] = 0x00 in all 127 commands
- SLAVE_FLAG byte[2] = 0x00 in all 62 responses
