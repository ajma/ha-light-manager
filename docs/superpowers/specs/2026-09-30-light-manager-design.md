# Light Manager: Design Spec

- **Date:** 2026-09-30
- **Status:** Approved in conversation, pending written-spec review
- **Deliverable:** A Home Assistant custom integration, installable via HACS

## 1. Purpose

Automatically control brightness and color temperature for groups of lights: a **day** setting, a **night** setting, and a gradual ramp between them at configurable times. Manual changes are detected and respected.

**Why build it:** the user tried Adaptive Lighting and wants their own integration for full control. Adaptive Lighting's configuration UI (about 40 options on one form) was confusing. A clear, short setup is a primary goal. Adaptive Lighting is a source of ideas only; debugging it is out of scope.

**Hardware to design for:** the user's lights include **Z-Wave dimmer switches** (brightness only, via Z-Wave JS). They report state late and mid-fade, and may not reach very low levels.

**Success criteria:**
1. A light group ramps smoothly from day to night (and back), ending exactly at the configured target time.
2. Touching one light during a ramp stops automation for that light only. The rest of the group continues.
3. Z-Wave dimmers are not falsely marked as overridden by their own late or clamped reports.
4. Creating a group takes two short form steps, and every visible field is relevant.
5. Global and per-group enable switches and Day now / Night now buttons behave as specified in §8.

## 2. Scope

**In scope:** everything in §4–§12.

**Out of scope (v1):**
- A custom sidebar panel or dashboard card (possible later; the architecture keeps logic in the backend)
- Intercepting `light.turn_on` service calls to prevent the turn-on flash
- Per-light timing, and a per-light turn-off setting
- Custom HA services (entities cover automation needs)
- Per-light enable switches
- YAML configuration

## 3. Terminology

| Term | Meaning |
|---|---|
| **Group** | A named set of lights sharing one schedule. One config subentry. |
| **Setpoint** | A (brightness %, color temp K) pair. Each group has a day and a night setpoint. |
| **Target time** | When a group must *arrive* at a setpoint. There's a day target and a night target. |
| **Transition** | The ramp between setpoints. It **ends** at the target time and lasts `transition_min` minutes. |
| **Phase** | `day`, `to_night`, `night`, or `to_day`. |
| **Hold** | The state created by Day now / Night now, which pins a phase until the next opposite ramp starts. |
| **AUTO / OVERRIDDEN** | A per-light state. AUTO lights follow the group; OVERRIDDEN lights are left alone. |
| **Active** | A group is active when both the global switch and the group's switch are on. |

## 4. Architecture

### 4.1 Integration shape

- **Domain:** `light_manager`. **Display name:** Light Manager.
- **Manifest:** `config_flow: true`, `single_config_entry: true`, `integration_type: "hub"`, `iot_class: "calculated"`.
- **One parent config entry**, created with no questions. It owns the global controls.
- **Each light group is a config subentry** (type `group`) of that parent. The integration page shows an **"Add light group"** button.
- **Devices:** the parent entry gets a "Light Manager" device, and each group gets a device named after the group.

### 4.2 Modules

```
custom_components/light_manager/
  __init__.py       setup/unload; builds the Manager from the parent entry + group subentries;
                    reloads on any entry/subentry change
  config_flow.py    parent ConfigFlow (no questions); GroupSubentryFlow (2 steps + reconfigure)
  const.py          domain, defaults, tolerances, tick/fade constants
  models.py         frozen dataclasses: GroupConfig, Setpoint, TargetTime, LightOverride, Phase
  schedule.py       PURE: (timing config, sun-time provider, now) -> Phase (+ progress, ramp windows)
  curve.py          PURE: (group setpoints, LightOverride, Phase, LightCapabilities) -> LightCommand
  light_tracker.py  PURE: per-light AUTO/OVERRIDDEN state machine and report classification
  group.py          GroupRuntime: timers, state listeners, drives trackers, sends commands, holds
  manager.py        Manager: owns GroupRuntimes, global enable, global buttons, persistence
  switch.py  button.py  sensor.py    thin entity wrappers over Manager / GroupRuntime
  manifest.json  strings.json  translations/en.json
hacs.json  pyproject.toml  tests/  .github/workflows/
```

**PURE** modules do not import Home Assistant. They receive plain values (datetimes, numbers, dataclasses) and return plain values. Sun times reach `schedule.py` through a small injected callable, so tests can supply fixed sunrise/sunset times.

### 4.3 Data flow

```
timer tick ─┐
light on ───┼─► GroupRuntime ─► schedule.py: phase now?
button ─────┘        │
                     ├─ per light: curve.py → target (brightness, color temp) for THIS light
                     ├─ light_tracker: AUTO? not already sent? → send, else skip
                     └─ light.turn_on(..., context=new Context())  (context ID recorded per light)
light state_changed ──► light_tracker.classify(report) → ours | manual → maybe OVERRIDDEN
call_service(light.turn_on with values) ──► remember context ID as "explicit turn-on"
```

## 5. Configuration

### 5.1 Per group vs per light

| Setting | Per group | Per light |
|---|---|---|
| Name, member lights | ✓ | |
| Day / night target time | ✓ | |
| Transition duration | ✓ | |
| Turn-off behavior for overridden lights | ✓ | |
| Day / night brightness | ✓ default | optional override |
| Day / night color temp | ✓ default | optional override |
| Color temp support, Kelvin range | | read from the light's attributes, never asked |

There are **no global settings**, only global controls (§8).

### 5.2 Parent entry

Adding the integration creates the parent entry immediately, with no form fields. A second instance is disallowed (`single_config_entry`).

### 5.3 "Add light group" subentry flow

**Step 1 of 2:**

| Field | Control | Default | Constraint |
|---|---|---|---|
| Name | text | — | required, unique among groups |
| Lights | entity picker, domain `light`, multiple | — | ≥1; no light (after group expansion, §10) in another group |
| Day brightness | number slider, % | 100 | 1–100 |
| Day color temp | color-temp slider, K | 4000 | 1500–6500 |
| Day target | radio: Sunrise / Fixed time | Sunrise | |
| Night brightness | number slider, % | 20 | 1–100 |
| Night color temp | color-temp slider, K | 2200 | 1500–6500 |
| Night target | radio: Sunset / Fixed time | Sunset | |
| Transition | number, minutes | 30 | 0–180 (0 = instant switch at the target) |
| When an overridden light is turned off | radio: Return to automatic / Stay overridden | Return to automatic | |

**Step 2 of 2 (Timing)** shows only the fields matching the step 1 choices:

| Choice | Field | Default | Constraint |
|---|---|---|---|
| Sunrise / Sunset | Offset, minutes (negative = earlier) | 0 | −180 to +180 |
| Fixed time | Time of day | 07:00 day / 21:00 night | |

**Validation (step 2):** if both targets are fixed times, they must differ, and the gap between them must be at least the transition length in both directions around the clock. Otherwise the error is "The transition is longer than the gap between the day and night targets."

Field help text appears under each field via translations.

### 5.4 Reconfigure a group

Reconfiguring a group opens a menu:
- **Edit group settings:** the same two steps, pre-filled.
- **Customize a light:**
  1. Pick one of this group's lights. The list shows actual bulbs, with Group helpers expanded into their members (§10), and customized lights are marked.
  2. A form with four optional fields: day brightness, day color temp, night brightness, night color temp. It's pre-filled with the light's current overrides, and the description shows the group values. Color temp fields are omitted for lights without color temp support. A blank field means "follow the group". Clearing all fields removes the customization.

Overrides for lights removed from the group are dropped when the group is saved.

### 5.5 Stored subentry data

```json
{
  "name": "Living room",
  "lights": ["light.lamp", "light.den_dimmer"],
  "day":   {"brightness_pct": 100, "color_temp_kelvin": 4000},
  "night": {"brightness_pct": 20,  "color_temp_kelvin": 2200},
  "day_target":   {"type": "sun",   "offset_min": 0},
  "night_target": {"type": "fixed", "time": "21:00:00"},
  "transition_min": 30,
  "off_behavior": "return_to_auto",
  "light_overrides": {
    "light.den_dimmer": {"night_brightness_pct": 5}
  }
}
```

`off_behavior` is `return_to_auto` or `stay_overridden`. Keys in a `light_overrides` entry are any subset of `day_brightness_pct`, `day_color_temp_kelvin`, `night_brightness_pct`, `night_color_temp_kelvin`.

## 6. Schedule and ramp

### 6.1 Target times

- **Sun:** day target = sunrise + offset; night target = sunset + offset. Computed with HA's configured location and timezone (`homeassistant.helpers.sun`).
- **Fixed:** a local wall-clock time, every day.

### 6.2 Phase determination

The phase is **recalculated from the clock** on every evaluation; there is no step counter.

1. Find the **next upcoming target** after `now` (the earlier of the next day target and the next night target).
2. Its **ramp window** is `[max(target − transition, previous opposite target), target]`. The previous opposite target is the latest target of the other kind before it. This makes a ramp shorter if the targets are closer together than the transition length.
3. If `now` is inside that window, the phase is `to_day` or `to_night` with `progress = (now − window_start) / (target − window_start)`. Otherwise the phase is the plateau before it (`night` if the next target is the day target, `day` if it's the night target).
4. If a sun event doesn't occur for a long time (polar day or night), the next target is simply far away and the group stays in its plateau.
5. `transition_min = 0` gives an empty window, meaning an instant switch at the target.

### 6.3 Interpolation (`curve.py`)

For each light:
1. **Effective setpoints:** each value is the light override if set, else the group value.
2. **Interpolate** at `progress` p (0 → 1), from the setpoint being left to the one being approached:
   - Brightness: linear in percent.
   - Color temp: linear in **mireds** (`1e6 / K`), then converted back to Kelvin.
3. **Limit to the light's capabilities** (§7.5).

Example, day 100%/4000 K to night 20%/2200 K over 30 minutes:

| Minute | 0 | 10 | 20 | 30 |
|---|---|---|---|---|
| Brightness | 100% | 73% | 47% | 20% |
| Color temp | 4000 K | 3143 K | 2588 K | 2200 K |

### 6.4 Command cadence

- **During a ramp:** evaluate every **30 s**. Each command uses `transition: 2` (seconds). A light is skipped if its rounded target equals the last value we sent it.
- **At the target time:** one final evaluation, landing exactly on the setpoint.
- **Outside ramps:** no periodic commands. Commands are sent only on light turn-on (§7.4), button presses, re-activation, and startup. At startup, AUTO lights that are on get the current target with a 2 s fade.
- **Timer:** each group has one self-rearming timer (`async_track_point_in_utc_time`). It always wakes at the earliest of these moments:
  - During a ramp: the next 30 s tick, or the target, whichever is sooner.
  - Otherwise: the next ramp start, or the target if the ramp is empty (transition 0).
  - The hold expiry, if a hold is active.
  - After a failed command, 30 s from the failure while the group is active, so the retry happens even outside a ramp (§10).

  Each wake recomputes everything from the clock, so a missed or late wake corrects itself. A group that has been stopped (entry unload or reload) never re-arms its timer, even if a command that was in flight fails afterwards.

### 6.5 Holds (Day now / Night now)

- Pressing a button applies that setpoint immediately (2 s fade) to every light that's on, clears all overrides in the group, and sets a hold.
- **Night now** holds `night` until the **next `to_day` ramp starts**. **Day now** holds `day` until the **next `to_night` ramp starts**. The hold's expiry is recalculated from `pressed_at` and the current config.
- While held, the phase sensor shows the held phase with `held: true`. A button pressed mid-ramp cancels that ramp.
- **"Current target"** everywhere in this spec means the held setpoint while a hold is active, and otherwise the scheduled phase's value (§6.2–6.3).
- A ramp suppressed by a hold (e.g. the `to_night` ramp while Night now is held) sends nothing and does **not** clear overrides.
- Examples: Night now at 12:00 holds night until tomorrow morning's ramp starts. Day now at 23:00 holds day until tomorrow evening's ramp starts.

## 7. Per-light control

### 7.1 States

Each member light has a tracker in state **AUTO** or **OVERRIDDEN**, plus:
- `expected`: the last values we sent. It's cleared when the light returns to AUTO, turns off or becomes unavailable, so the current target is always resent afterwards.
- `pre_command`: the light's reported values just before our last command
- `sent_at` and `fade_s` of our last command
- the context IDs of our recent commands to this light

### 7.2 Classifying a state report

This applies only to reports where the light is on both before and after (on/off changes are handled in §7.3–7.4). A report is **manual** if any of these changes and the change is not explained:
- **brightness**
- **color temp**, for lights with native `color_temp` support
- **color mode** moving away from `color_temp` to an RGB/HS/XY mode, for lights with native `color_temp` support

A change is **explained (ours)** if any of these holds:
1. **Context:** the report's context ID is one of our recent command contexts for this light.
2. **Tolerance:** the value is within tolerance of `expected`. Tolerances are **±5 of 255 brightness (≈2%)** and **±10 mireds**.
3. **Settling:** the report arrives within `sent_at + fade_s + 10 s`, and the value lies between `pre_command` and `expected` (inclusive, ± the same tolerance). This covers Z-Wave dimmers that report mid-fade, report late, or stop above the requested minimum.

A manual report sets the light to **OVERRIDDEN**. Classification runs whenever the group is active, not only during ramps. When the group is inactive, reports are ignored.

The tolerances, the 10 s settle window, the 30 s tick and the 2 s fade are constants in `const.py`, to be tuned against real hardware.

### 7.3 Back to AUTO

- **Turned off:** if `off_behavior = return_to_auto`, the light becomes AUTO. If `stay_overridden`, it stays OVERRIDDEN.
- **Start of the next ramp** (either direction, unless suppressed by a hold, §6.5): all overrides in the group are cleared. Lights that are on join at the ramp's current value, which may be a visible jump.
- **Day now / Night now** (group, or global for enabled groups): all overrides in the group are cleared.
- **Group becomes active again:** all overrides in the group are cleared.

### 7.4 Turn-on handling

A light going from `off` to `on`:
- **Explicit turn-on:** the state change's context ID matches a recent `light.turn_on` / `light.toggle` service call whose data included brightness (`brightness`, `brightness_pct`, `brightness_step`, `brightness_step_pct`), color (`color_temp_kelvin`, `hs_color`, `xy_color`, `rgb_color`, `rgbw_color`, `rgbww_color`, `color_name`, `white`), or `profile`. The light becomes **OVERRIDDEN**. This covers scenes, automations and dashboard sliders. Explicit-call context IDs are kept for 10 s.
- **Otherwise** (wall switch, plain turn-on, voice): if the light is OVERRIDDEN with `stay_overridden`, it's left alone. Otherwise it becomes AUTO and is sent the current target **with no fade** (`transition: 0`).
A light going from `unavailable`/`unknown` to `on` isn't a turn-on. It keeps its previous AUTO/OVERRIDDEN state, and if AUTO, it gets the current target with no fade.
- **Known limitation:** a light switched on outside HA shows its previous level briefly before correction.

### 7.5 Capabilities

Capabilities are read from each light's state attributes on every evaluation:
- **Native `color_temp` in `supported_color_modes`:** send `brightness` and `color_temp_kelvin`, clamped to `min_color_temp_kelvin`–`max_color_temp_kelvin`.
- **Color modes without `color_temp`** (HS/XY/RGB-family only): send `color_temp_kelvin`, which HA core converts to the light's color mode (verified, §13). Only brightness is used for manual detection.
- **Brightness only:** send `brightness` only.
- **On/off only:** never commanded; logged once at debug level.
- **Brightness** is sent as `brightness` (1–255) = `max(1, round(pct × 255 / 100))`.

## 8. Entities

| Entity | Global (Light Manager device) | Per group (e.g. "Living room") |
|---|---|---|
| Enable switch | `switch.light_manager_automatic` | `switch.living_room_automatic` |
| Day now button | `button.light_manager_day_now` | `button.living_room_day_now` |
| Night now button | `button.light_manager_night_now` | `button.living_room_night_now` |
| Phase sensor | — | `sensor.living_room_phase` |

- `has_entity_name = True`. Names come from the device, and unique IDs are derived from the entry/subentry IDs, so renaming a group doesn't change entity IDs.
- **Phase sensor:** `device_class: enum`, options `day`, `to_night`, `night`, `to_day`. Attributes:
  - `progress`: int 0–100 during a ramp, else `null`
  - `held`: bool
  - `next_day_target`, `next_night_target`: ISO datetimes
  - `overridden_lights`: list of entity IDs

  The sensor keeps showing the scheduled (or held) phase while the group is inactive.

**Enable switches:**
- A group is **active** only if both the global switch and its own switch are on.
- **Inactive** groups send no automatic commands (no ramps, no turn-on handling) and don't classify reports.
- **Becoming active** (either switch turned on) clears all overrides in each newly active group and sends the current target to its lights that are on (2 s fade).
- New groups start with their switch on.

**Buttons:**
- A **group** Day now / Night now always works, even when the group is inactive (§6.5). "Disabled" stops *automatic* changes; a button press is manual. When the group is inactive, no automatic changes follow the press.
- A **global** Day now / Night now acts on **every group whose own switch is on**, regardless of the global switch.

**No custom services.** Automations use `switch.*` and `button.press`.

## 9. Persistence

One `homeassistant.helpers.storage.Store` per parent entry, key `light_manager.<entry_id>`:

```json
{
  "global_enabled": true,
  "groups": {
    "<subentry_id>": {
      "enabled": true,
      "hold": {"phase": "night", "pressed_at": "2026-09-30T12:00:00+00:00"},
      "overridden": {"light.lamp": "2026-09-30T18:40:00+00:00"}
    }
  }
}
```

**On load:**
- A hold is kept only if its expiry (§6.5, recomputed) is still in the future.
- An override is kept only if no override-clearing ramp start (§7.3) occurred between its timestamp and now. For `return_to_auto`, the light also must not be known to be `off`. A light whose state is missing or `unavailable` at load keeps its override; Z-Wave lights often appear after Light Manager starts.
- Groups that exist in the store but no longer exist as subentries are dropped.

Saves are debounced (`Store.async_delay_save`).

## 10. Error handling

- **Unavailable/unknown lights:** skipped; state kept (§7.4).
- **Failed service calls:** log a warning and roll `expected` back to its value before the command, then wake 30 s later to retry (§6.4). If something newer replaced `expected` while the call was in flight (another command, return to AUTO, turn-off, unavailable), the rollback is skipped so the newer state stands (§7.1). Failures never mark a light overridden.
- **Lights deleted from HA:** skipped with one warning per load. Other lights continue working.
- **HA light groups:** a member that is an HA Group-helper light (entity registry platform `group`, with an `entity_id` attribute) is **expanded into its member lights**. Membership changes are picked up by listening to the group entity's state. Groups from other systems (Hue rooms, Zigbee2MQTT groups) are treated as single lights.
- **Form validation:** see §5.3.
- **Any entry or subentry change** reloads the integration. State is recomputed from the clock and restored from the Store.
- **Debug logging** records each decision, e.g. `light.den_dimmer: report 10% → ours (rule 3: between 12% and 5%)`.

## 11. Testing

- **Stack:** pytest, `pytest-homeassistant-custom-component` pinned to the newest stable HA release, and the `freezer` fixture with `async_fire_time_changed`.
- **Unit tests (no HA):**
  - `schedule`: every phase boundary; sun offsets ±; fixed times; ramps shortened when targets are close; a missing sun event; transition 0; hold expiry.
  - `curve`: the §6.3 table; per-light overrides (partial and full); Kelvin clamping; brightness-only; on/off-only.
  - `light_tracker`: Z-Wave scenarios (late report with a fresh context; mid-fade reports; settling at 10% when 5% was asked; user sets 100%; a nudge within tolerance; a nudge within the settle band); both `off_behavior` values; explicit vs plain turn-on; unavailable round trip.
- **Integration tests (HA test instance):**
  - Fake lights: states set via `hass.states.async_set` plus a registered fake `light.turn_on` service that records calls and writes resulting states with a configurable delay and context, to simulate Z-Wave timing.
  - Config flow: parent creation, both group steps, every validation error, the reconfigure menu, and "Customize a light".
  - A full 30-minute ramp driven by the fake clock, checking commands per tick.
  - Entities: switch/button semantics from §8, sensor states and attributes, restore after restart (§9).
- **CI:** a GitHub Actions workflow (`ci.yml`) running ruff, pytest, `hassfest` and HACS validation on pushes to `main` and on pull requests.
- **Final acceptance:** manual install on the user's HA with their Z-Wave dimmers.

## 12. Packaging

- `custom_components/light_manager/` layout with `manifest.json` (`version`, `codeowners`, `documentation`, `issue_tracker`, `requirements: []`).
- `hacs.json` at the repo root.
- `pyproject.toml` with pytest and ruff config. Python version and dependency versions match the newest stable HA release (§13).
- **Releases** come from a manual GitHub Actions workflow (`release.yml`, input `bump`: patch/minor/major). It runs CI and then:
  1. Bumps `version` in `manifest.json`.
  2. Commits `Release vX.Y.Z` as the person who started it.
  3. Tags the commit and pushes the commit and tag together.
  4. Publishes a GitHub release with `light_manager.zip`.
- `hacs.json` sets `zip_release`, so HACS installs from that asset. The manifest starts at `0.0.0`; the first release uses `minor` (v0.1.0).

## 13. Verified during planning

All items were checked against Home Assistant 2026.9.4. No fallbacks are needed.

| Item | Result |
|---|---|
| How long an entity keeps a service call's context | `CONTEXT_RECENT_TIME_SECONDS = 5`. Rules 2–3 (§7.2) cover reports that arrive later. |
| Menus inside subentry reconfigure flows | Supported. The reconfigure flow is a menu (§5.4). |
| `config_subentry_id` in `async_add_entities` | Supported. Group devices and entities belong to their subentry. |
| `EVENT_CALL_SERVICE` for every service call | Fired by the service registry for every call, including those made by scenes and automations, with the caller's context. |
| HA core converting `color_temp_kelvin` for color lights without `color_temp` | Yes; the light component converts it to the light's color mode. |
| Newest stable HA release, its Python version, and the matching test package | HA 2026.9.4, Python ≥ 3.14.2, `pytest-homeassistant-custom-component` 0.13.367. |

## 14. Decisions made during design

**Chosen by the user:**
- Custom integration, not an add-on
- Two buttons plus a phase sensor instead of one toggle
- Per-light override scope
- Back to AUTO when turned off or at the next ramp start
- Transition ends at the target time, called "target time"
- Group defaults plus per-light brightness/color temp overrides
- Two-step setup form
- Parent entry with group subentries
- HA built-in forms (no custom panel)
- A configurable per-group turn-off behavior

**Ruled on the user's behalf (approved within design sections):**
- Mired interpolation for color temp; linear brightness
- 30 s tick, 2 s step fade, instant fade on turn-on
- Tolerances (±2% brightness, ±10 mireds, 10 s settle window)
- Explicit turn-on (scene, slider) starts OVERRIDDEN
- Group buttons work while the group is inactive
- Global buttons skip groups whose own switch is off
- Overrides and holds persist across restarts
- HA Group-helper lights expanded into members
- Ranges: brightness 1–100%, color temp 1500–6500 K, offset ±180 min, transition 0–180 min
- Defaults: day 100%/4000 K at sunrise, night 20%/2200 K at sunset, 30 min transition
- Entity naming `…_automatic`, `…_day_now`, `…_night_now`, `…_phase`

**Ruled during planning (on the user's behalf):**
- One self-rearming timer per group instead of separate interval and point-in-time timers (§6.4)
- Returning to AUTO clears `expected`, so the same target is resent (§7.1)
- Restore drops a `return_to_auto` override only when the light is known to be off (§9)
- A failed command never blocks other lights; any exception rolls the light back and the group retries it 30 s later, including outside ramps. (Changed during implementation: the planned "retry at the next evaluation" left a light that failed on a midday button press wrong until the evening ramp.)
- When a sun event doesn't occur (polar regions), so two targets of the same kind come in a row, the group stays at that setting with no ramp. With no targets at all, it stays at day
- Releases are GitHub releases built by a manual workflow; the repository owner is `ajma`
