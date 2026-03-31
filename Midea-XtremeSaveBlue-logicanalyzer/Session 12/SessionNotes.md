# Session 12 — Session Notes

Cool mode testing with mode switching, ECO, turbo, fan gear percentages, vane
positions, anti-direct wind ("direktes Anblasen verhindern"), night mode, and
Follow Me. All Celsius. Includes IR remote for temperature and swing.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 10-11 — all buses + IR
- **Logic analyser**: Saleae
- **Wi-Fi dongle**: CONNECTED, paired with app
- **Wired controller**: KJR-120M
- **IR remote**: Standard Midea IR remote (Celsius mode)

---

## Initial state

- **System power**: ON
- **Mode**: Heat
- **Setpoint**: 24 C
- **Outdoor temp**: ~4 C (app report)
- **Indoor temp**: ~25.4 C (app report)

---

## Operator action log

Reconstructed from [Session 12 Quicknotes.md](Session%2012%20Quicknotes.md) with
protocol timestamps.

### Phase 1 — Mode switching + ECO + Turbo (t=0-170 s)

| Time (s) | Action | Source | Protocol observation |
|----------|--------|--------|---------------------|
| 0        | Start recording, Heat mode 24 C | — | byte[8]=0x84 (Heat), byte[10]=0x58 (24 C) |
| 16       | Set temp 23 C | App | |
| 25       | Set mode Cool | App | byte[8] 0x84->0x88 |
| ~35      | Set mode ECO | App | 0xC0 ECO=yes at t=54 |
| ~55      | Set mode Turbo, stops ECO | App | body[8] Turbo=yes, ECO=no |
| ~60      | Set gear (gang) 50% | App | |
| ~65      | Set gear 75% | App | |
| ~70      | Disable gang | App | |
| ~75      | Set Turbo | App | |
| 158      | Set 22 C | App | |
| 167      | Disable Turbo | App | |

### Phase 2 — ECO + LED issues (t=170-330 s)

| Time (s) | Action | Source | Protocol observation |
|----------|--------|--------|---------------------|
| ~170     | Somewhere in between the LED was turned off? App fault? | — | |
| ~180     | Turn on ECO, set 22 C | App | |
| ~190     | Setting temp disables ECO! | App | Confirmed: ECO disappears after temp change |
| ~200     | Turn on ECO again, then off | App | |
| ~210     | Set vane position medium each | App | Swing: Off in UART (not visible on UART bus) |
| ~220     | Set vane to uppest left | App | |
| ~230     | Unit lost its beeping somewhere? A bit was stuck? | — | |

### Phase 3 — IR remote + swing (t=330-460 s)

| Time (s) | Action | Source | IR frame |
|----------|--------|--------|----------|
| 331      | Use IR to set 22 C | IR | B24DBF40**50**AF (22 C, bit4=1) |
| 332      | Auto swing | IR | B24DBF40**70**8F (23 C, bit4=1) |
| ~350     | "Direktes Anblasen verhindern" (anti-direct wind) | App/IR | |
| 407      | 21 C via remote? | IR | B24DBF40**60**9F (23 C per formula, but quicknote says 21) |
| ~420     | "App hat wieder das LED bit verlernt" (app lost LED state again) | — | |
| ~430     | "App killen" (kill app) | — | |
| 449      | Remote 21 C | IR | B24DBF40**20**DF (21 C) |
| 451      | Remote press again | IR | B24DBF40**30**CF (21 C, bit4=1) |
| 457      | Remote press again | IR | B24DBF40**20**DF (21 C) |

### Phase 4 — Recovery + Night mode + Follow Me (t=460-663 s)

| Time (s) | Action | Source | Protocol observation |
|----------|--------|--------|---------------------|
| ~470     | Various changes, beep came back after LED slider went on again | App | |
| ~500     | Set 22 C, beeps again | App | |
| ~510     | "Direktes Anblasen verhindern" off | App | |
| 584      | Night mode on (room controller) | Wall ctrl | CosySleepSw=yes, Sleep=yes |
| ~590     | Set 21 C | App | |
| 628      | Follow Me activated on controller, says 24 C | Wall ctrl | body[5]=0x62 (24.0 C) |
| 663      | End of session | — | |

---

## Session environment

- **Outdoor temp**: ~4 C (app report at start)
- **Indoor temp**: ~25.4 C (app report at start)
- **Session duration**: ~663 s (~11.1 min)
- **Total frames captured**: 15,138 (incl. 18 IR frames)

---

## Analysis

See [findings.md](findings.md) for the full analysis results.
