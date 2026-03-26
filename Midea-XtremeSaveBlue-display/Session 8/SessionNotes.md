# Session 8 — Session Notes (Operator Log)

Swing (vane) control investigation. Primary goal: decode swing on/off and fixed vane
position bytes on both XYE (HAHB) and UART buses. Secondary: mode and temp changes
via the app to compare UART command path vs wired controller path.

---

## Hardware under test

- **Unit**: Midea XtremeSaveBlue split A/C (test object)
- **Capture point**: Same bus setup as Sessions 4–7 — all internal display board buses
- **Logic analyser**: Saleae
- **Wi-Fi stick**: CONNECTED (used for app-based swing and temp control)
- **Wired controller**: KJR-12x (used for initial swing on/off toggle)

---

## Probe setup

Same channel configuration as Session 6/7.

---

## Follow-Me configuration

- **Active**: NO (disabled at end of Session 7, not re-enabled)

---

## Initial state (at capture start)

- **System power**: ON
- **Mode**: Auto (`0x90`)
- **Setpoint**: 30 °C (`0x5E`)
- **Fan**: Auto (`0x80`)
- **Swing vertical**: Off
- **Swing horizontal**: Off

---

## Operator action sequence

### Phase 1 — Swing toggle via wired controller (KJR-12x)

The KJR-12x supports only swing on/off (auto oscillation), not fixed vane positions.

| Step | Action | Control | Expected observation |
|------|--------|---------|---------------------|
| 1 | Start recording, no changes | — | Baseline: Auto/30 °C |
| 2 | Swing horizontal (L/R): Off → On | KJR-12x | Swing LR auto oscillation starts |
| 3 | Swing horizontal (L/R): On → Off | KJR-12x | Swing LR auto oscillation stops |
| 4 | Swing vertical (U/D): Off → On | KJR-12x | Swing UD auto oscillation starts |
| 5 | Swing vertical (U/D): On → Off | KJR-12x | Swing UD auto oscillation stops |

### Phase 2 — Swing toggle via app (UART Wi-Fi stick)

Same swing on/off as Phase 1, but sent from the phone app through the Wi-Fi module.
Swing auto oscillation set via app was visible on the KJR-12x display (status synced).

| Step | Action | Control | Expected observation |
|------|--------|---------|---------------------|
| 6 | Swing horizontal (L/R): Off → On | App | UART command → relayed to HAHB |
| 7 | Swing horizontal (L/R): On → Off | App | |
| 8 | Swing vertical (U/D): Off → On | App | |
| 9 | Swing vertical (U/D): On → Off | App | |

### Phase 3 — Fixed vane positions via app (UART Wi-Fi stick)

The app allows setting fixed vane angles (not available on the wired KJR-12x).
These fixed positions were NOT visible on the KJR-12x display — only the auto
oscillation state is synced to the wired controller.

**Vertical vane positions (up/down):**

| Step | Action | Control |
|------|--------|---------|
| 10 | Vane vertical: highest | App |
| 11 | Vane vertical: medium-high | App |
| 12 | Vane vertical: medium | App |
| 13 | Vane vertical: lower | App |
| 14 | Vane vertical: lowest | App |
| 15 | Vane vertical: lower (back up) | App |
| 16 | Vane vertical: medium | App |

**Horizontal vane positions (left/right):**

| Step | Action | Control |
|------|--------|---------|
| 17 | Vane horizontal: left | App |
| 18 | Vane horizontal: left/center | App |
| 19 | Vane horizontal: center | App |
| 20 | Vane horizontal: right/center | App |
| 21 | Vane horizontal: right | App |
| 22 | Vane horizontal: right/center (back) | App |

### Phase 4 — Temperature and mode changes via app

| Step | Action | Control | Expected state after |
|------|--------|---------|---------------------|
| 23 | Setpoint 30 → 29 °C | App | Auto / 29 °C |
| 24 | Mode: Auto → Heat | App | Heat / 29 °C |
| 25 | Setpoint 29 → 28 °C | App | Heat / 28 °C |
| 26 | Mode: Heat → Auto | App | Auto / 28 °C |
| 27 | Setpoint 28 → 16 °C | App | Auto / 16 °C (jump, not single-step!) |
| 28 | Setpoint 16 → 21 °C | App | Auto / 21 °C (jump) |
| 29 | Mode: Auto → Fan | App | Fan / 21 °C |
| 30 | Stop recording | — | — |

> Note: Steps 27–28 are direct temperature jumps via the app slider, not +1/−1 steps.
> The UART command will show the final value directly; XYE C3 may show intermediate
> values if the display board steps internally, or the final value only.

---

## Key analysis targets

1. **Swing on/off byte identification**: Compare XYE C3/C0 bytes during Phase 1 (wired) and Phase 2 (app). Session 7 found C3 response byte[20] bit2 = vertical swing. This session should confirm and find horizontal swing bit.
2. **Swing on/off: wired vs app path**: Do both produce the same XYE byte changes? Does the app command arrive via UART first, then get relayed to HAHB?
3. **Fixed vane position encoding**: Phase 3 exercises 5 vertical + 5 horizontal positions. These are app-only (UART 0x40 Set command) — look for body bytes that change with each position step.
4. **Vane position on XYE bus**: Do fixed vane positions appear on the HAHB XYE bus at all, or only on UART? (The KJR-12x didn't show them.)
5. **App temperature jumps**: Steps 27–28 jump multiple degrees. Does the UART send one command with the final value, or multiple incremental commands?
6. **Auto mode (0x90) on XYE**: Session 7 saw only 2 frames. This session starts in Auto mode — should have many more examples.
