# Light Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Home Assistant custom integration, `light_manager`, that moves groups of lights between day and night brightness and color temperature on a sun or clock schedule. Ramps end at the target time, manual changes are detected per light, and switches, buttons and a phase sensor control it.

**Architecture:**
- **Config:** one parent config entry (no questions) with one config **subentry** per light group.
- **Pure modules** (`schedule`, `curve`, `light_tracker`, `models`, `const`) hold the math and the override rules, and are unit-tested without HA.
- **Runtime:** a `Manager` owns one `GroupRuntime` per subentry. Each runtime runs a single self-rearming timer, listens to its lights' state changes and persists holds, overrides and switch states in a `Store`.
- **Entities** are thin views over the runtime.

**Tech Stack:**
- Python 3.14 and Home Assistant 2026.9.4.
- Tests: `pytest-homeassistant-custom-component` 0.13.367 (pytest, freezer).
- Tooling: ruff 0.16.9 and uv.
- CI: GitHub Actions, hassfest and the HACS action.

**Spec:** `docs/superpowers/specs/2026-09-30-light-manager-design.md`. Read it before starting; section numbers (§) below refer to it.

## Global Constraints

- **Commits:** plain author commits only. **Never add a `Co-Authored-By` trailer**, a "Generated with Claude" footer, a 🤖 line, or any AI attribution in commit messages, PR descriptions or issue bodies.
  - This overrides any harness attribution reminder; it is settled, not a conflict to weigh or ask about.
  - Before finishing a task, `git log --grep='Co-Authored-By' -i` must print nothing.
- **Versions:** always the newest stable major version of every tool, with no RCs or betas. The pins below were verified on 2026-09-30; don't downgrade them:
  - `requires-python = ">=3.14.2"`, `.python-version` `3.14`
  - `pytest-homeassistant-custom-component==0.13.367` (Home Assistant 2026.9.4)
  - `ruff==0.16.9`
  - `actions/checkout@v7`, `astral-sh/setup-uv@v10.2.0` (this repo has no floating `v10` tag), `hacs/action@22.5.0`, `home-assistant/actions/hassfest@master` (the documented ref; its only release is from 2020)
- **Integration basics:** the domain is `light_manager` and the code lives in `custom_components/light_manager/`. The manifest has `"requirements": []` and starts at `"version": "0.0.0"`.
- **Pure modules:** `const.py`, `models.py`, `schedule.py`, `curve.py` and `light_tracker.py` import nothing from `homeassistant`.
- **Times:** internal datetimes are timezone-aware UTC. Local wall-clock time is used only for fixed target times, through `dt_util.get_default_time_zone()`.
- **Every commit:** `uv run ruff format --check .`, `uv run ruff check .` and `uv run pytest -q` all pass.
- **Copy the code exactly.** Every file in this plan was written and run before the plan was assembled: the full suite (154 tests), ruff, hassfest and actionlint all passed on it. If a step's result differs from what the plan says, stop and report the output instead of redesigning.
- **Translations** are English literal strings. `strings.json` and `translations/en.json` are identical.
- **Entity IDs** follow spec §8. Unique IDs derive from the entry and subentry IDs, never from names.

## Review Focus

These are the inputs most likely to bite a real user. Each one is pinned by tests in the task that owns the code:

1. **DST changeover with fixed target times:** a 07:00 target stays at 07:00 local on both sides of the change, and the ramp still lasts the configured length.
   - `test_fixed_targets_follow_wall_clock_across_dst` (Task 2).
2. **Return to automatic when the target equals the last command sent** (a stale `expected`): the light must still be sent the command, or it stays at the user's value.
   - `test_reset_auto_forces_resend_of_same_target` (Task 4).
   - `test_overridden_light_off_and_on_returns_to_auto` and `test_press_resends_a_target_equal_to_the_last_command` (Task 5).
3. **A light that reports `brightness: None` while on** (Z-Wave during a refresh) must not count as a manual change.
   - `test_brightness_none_while_on_is_not_a_change` (Task 4).
   - `test_brightness_none_report_while_on_is_not_an_override` (Task 5).
4. **Z-Wave lights that load after Light Manager:** no crash, the target is sent when the light appears, and stored overrides are kept.
   - `test_light_missing_at_startup_gets_target_when_it_appears` and `test_override_kept_while_light_has_not_loaded_yet` (Task 5).
5. **A light whose command fails** (timeout, dead node) must not block the other lights, and must be retried.
   - `test_failed_command_is_rolled_back_so_it_retries` (Task 4).
   - `test_failed_command_does_not_block_others_and_is_retried` (Task 5).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `.python-version`, `uv.lock` | Python version, pinned dev dependencies, pytest and ruff config | 1 |
| `custom_components/light_manager/manifest.json` | Integration metadata (single config entry, config flow) | 1 |
| `custom_components/light_manager/const.py` | Config keys, defaults, limits, tuning constants | 1 |
| `custom_components/light_manager/models.py` | `Phase` and frozen config models parsed from subentry data | 1 |
| `custom_components/light_manager/schedule.py` | Target times, ramp windows, phase at a moment, hold expiry | 2 |
| `custom_components/light_manager/curve.py` | Setpoint interpolation; per-light capabilities and commands | 3 |
| `custom_components/light_manager/light_tracker.py` | Per-light AUTO/OVERRIDDEN state and report classification (§7) | 4 |
| `custom_components/light_manager/members.py` | Expand Group helpers into member lights | 5 |
| `custom_components/light_manager/group.py` | `GroupRuntime`: timer, state listener, commands, holds, restore | 5 |
| `custom_components/light_manager/manager.py` | `Manager`: all groups, global switch, explicit-turn-on contexts, Store | 5 |
| `custom_components/light_manager/__init__.py` | Entry setup/unload, reload on any change | 1, 5, 7 |
| `custom_components/light_manager/config_flow.py` | Parent flow; group subentry flow (add, reconfigure menu, customize) | 1, 6 |
| `custom_components/light_manager/strings.json`, `translations/en.json` | UI text | 6, 7 |
| `custom_components/light_manager/entity.py`, `switch.py`, `button.py`, `sensor.py`, `icons.json` | Entities (§8) | 7 |
| `tests/…` | Unit and integration tests | 1–7 |
| `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `hacs.json`, `README.md` | CI, releases, HACS | 8 |

---

### Task 1: Project scaffold, constants and config models

**Files:**
- Create: `pyproject.toml`, `.python-version`, `uv.lock` (generated)
- Create: `custom_components/light_manager/manifest.json`, `__init__.py`, `config_flow.py`, `const.py`, `models.py`
- Create: `tests/__init__.py`, `tests/conftest.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `const.py`: every `CONF_*` key, `DEFAULT_*`, `MIN_*`/`MAX_*`, `OVERRIDE_KEYS`, `TARGET_SUN`/`TARGET_FIXED`, `OFF_RETURN_TO_AUTO`/`OFF_STAY_OVERRIDDEN`, `SUBENTRY_TYPE_GROUP = "group"`, and the tuning constants:
    - `TICK_SECONDS = 30`, `STEP_FADE_SECONDS = 2`, `SETTLE_SECONDS = 10`
    - `BRIGHTNESS_TOLERANCE = 5`, `MIRED_TOLERANCE = 10`
    - `EXPLICIT_CONTEXT_SECONDS = 10`, `RECENT_CONTEXTS = 5`
    - `STORAGE_VERSION = 1`, `SAVE_DELAY_SECONDS = 1`
  - `models.py`:
    - `Phase(StrEnum)` with `DAY="day"`, `TO_NIGHT="to_night"`, `NIGHT="night"`, `TO_DAY="to_day"`; `RAMP_PHASES`.
    - `Setpoint(brightness_pct: int, color_temp_kelvin: int)`.
    - `TargetTime(type: str, offset: timedelta = 0, time: dt.time | None = None)`.
    - `LightOverride(day_brightness_pct, day_color_temp_kelvin, night_brightness_pct, night_color_temp_kelvin)`, all `int | None`.
    - `GroupConfig(name, lights: tuple[str, ...], day, night, day_target, night_target, transition: timedelta, off_behavior: str, light_overrides: Mapping[str, LightOverride])`.
    - Each model has a `from_data(Mapping) -> Self` classmethod.
  - `config_flow.py` (minimal): `LightManagerConfigFlow` creates the parent entry without questions. Task 6 extends it.
    - It's needed now because `manifest.json` declares `config_flow: true`, and HA refuses to set up the entry without it.

- [ ] **Step 1: Project files**

Create `pyproject.toml`:

```toml
[project]
name = "ha-light-manager"
version = "0.0.0"
description = "Home Assistant integration: day/night brightness and color temperature for light groups"
requires-python = ">=3.14.2"
dependencies = []

[dependency-groups]
dev = [
    "pytest-homeassistant-custom-component==0.13.367",
    "ruff==0.16.9",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
target-version = "py314"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
```

Create `.python-version`:

```text
3.14
```

Run: `uv lock && uv sync`
Expected: creates `uv.lock` and `.venv` with Python 3.14, Home Assistant 2026.9.4 and ruff 0.16.9. (`.gitignore` already ignores `.venv/` and caches.)

- [ ] **Step 2: Integration skeleton and test setup**

Create `custom_components/light_manager/manifest.json`:

```json
{
  "domain": "light_manager",
  "name": "Light Manager",
  "codeowners": [
    "@ajma"
  ],
  "config_flow": true,
  "documentation": "https://github.com/ajma/ha-light-manager",
  "integration_type": "hub",
  "iot_class": "calculated",
  "issue_tracker": "https://github.com/ajma/ha-light-manager/issues",
  "requirements": [],
  "single_config_entry": true,
  "version": "0.0.0"
}
```

The manifest is kept in `jq`'s output format, so the release workflow's version bump is a one-line diff.

Create `custom_components/light_manager/__init__.py`:

```python
"""Light Manager: day/night brightness and color temperature for light groups."""
```

Create `custom_components/light_manager/config_flow.py`:

```python
"""Config flow for Light Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class LightManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """The parent entry: created with no questions (spec §5.2)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(title="Light Manager", data={})
```

Create `tests/__init__.py`:

```python
"""Tests for Light Manager."""
```

Create `tests/conftest.py`:

```python
"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load custom_components/ in every test that uses hass."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_models.py`:

```python
"""Tests for models.py."""

import datetime as dt

from custom_components.light_manager.models import (
    GroupConfig,
    LightOverride,
    Phase,
    Setpoint,
    TargetTime,
)

DATA = {
    "name": "Living room",
    "lights": ["light.lamp", "light.den_dimmer"],
    "day": {"brightness_pct": 100, "color_temp_kelvin": 4000},
    "night": {"brightness_pct": 20, "color_temp_kelvin": 2200},
    "day_target": {"type": "sun", "offset_min": -15},
    "night_target": {"type": "fixed", "time": "21:00:00"},
    "transition_min": 30,
    "off_behavior": "return_to_auto",
    "light_overrides": {"light.den_dimmer": {"night_brightness_pct": 5}},
}


def test_group_config_from_spec_example() -> None:
    config = GroupConfig.from_data(DATA)

    assert config.name == "Living room"
    assert config.lights == ("light.lamp", "light.den_dimmer")
    assert config.day == Setpoint(100, 4000)
    assert config.night == Setpoint(20, 2200)
    assert config.day_target == TargetTime("sun", offset=dt.timedelta(minutes=-15))
    assert config.night_target == TargetTime("fixed", time=dt.time(21, 0))
    assert config.transition == dt.timedelta(minutes=30)
    assert config.off_behavior == "return_to_auto"
    assert config.light_overrides == {
        "light.den_dimmer": LightOverride(night_brightness_pct=5)
    }


def test_numbers_from_selectors_become_ints() -> None:
    data = {
        **DATA,
        "day": {"brightness_pct": 55.0, "color_temp_kelvin": 3000.0},
        "transition_min": 10.0,
        "light_overrides": {"light.lamp": {"day_color_temp_kelvin": 2700.0}},
    }

    config = GroupConfig.from_data(data)

    assert config.day == Setpoint(55, 3000)
    assert type(config.day.brightness_pct) is int
    assert config.transition == dt.timedelta(minutes=10)
    assert config.light_overrides["light.lamp"] == LightOverride(
        day_color_temp_kelvin=2700
    )


def test_missing_overrides_and_offset_default() -> None:
    data = {k: v for k, v in DATA.items() if k != "light_overrides"}
    data["day_target"] = {"type": "sun"}

    config = GroupConfig.from_data(data)

    assert config.light_overrides == {}
    assert config.day_target.offset == dt.timedelta(0)


def test_light_override_ignores_none_and_unknown_keys() -> None:
    override = LightOverride.from_data(
        {"day_brightness_pct": None, "night_color_temp_kelvin": 2000, "x": 1}
    )

    assert override == LightOverride(night_color_temp_kelvin=2000)


def test_phase_values_are_sensor_states() -> None:
    assert [p.value for p in Phase] == ["day", "to_night", "night", "to_day"]
```

- [ ] **Step 4: Run it to see it fail**

Run: `uv run pytest tests/test_models.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'custom_components.light_manager.models'`.

- [ ] **Step 5: Implement constants and models**

Create `custom_components/light_manager/const.py`:

```python
"""Constants for Light Manager."""

from typing import Final

DOMAIN: Final = "light_manager"
SUBENTRY_TYPE_GROUP: Final = "group"

# Subentry data keys (spec §5.5)
CONF_NAME: Final = "name"
CONF_LIGHTS: Final = "lights"
CONF_DAY: Final = "day"
CONF_NIGHT: Final = "night"
CONF_BRIGHTNESS_PCT: Final = "brightness_pct"
CONF_COLOR_TEMP_KELVIN: Final = "color_temp_kelvin"
CONF_DAY_TARGET: Final = "day_target"
CONF_NIGHT_TARGET: Final = "night_target"
CONF_TYPE: Final = "type"
CONF_OFFSET_MIN: Final = "offset_min"
CONF_TIME: Final = "time"
CONF_TRANSITION_MIN: Final = "transition_min"
CONF_OFF_BEHAVIOR: Final = "off_behavior"
CONF_LIGHT_OVERRIDES: Final = "light_overrides"

TARGET_SUN: Final = "sun"
TARGET_FIXED: Final = "fixed"

OFF_RETURN_TO_AUTO: Final = "return_to_auto"
OFF_STAY_OVERRIDDEN: Final = "stay_overridden"

OVERRIDE_KEYS: Final = (
    "day_brightness_pct",
    "day_color_temp_kelvin",
    "night_brightness_pct",
    "night_color_temp_kelvin",
)

# Defaults (spec §5.3)
DEFAULT_DAY_BRIGHTNESS_PCT: Final = 100
DEFAULT_DAY_COLOR_TEMP_KELVIN: Final = 4000
DEFAULT_NIGHT_BRIGHTNESS_PCT: Final = 20
DEFAULT_NIGHT_COLOR_TEMP_KELVIN: Final = 2200
DEFAULT_TRANSITION_MIN: Final = 30
DEFAULT_DAY_TIME: Final = "07:00:00"
DEFAULT_NIGHT_TIME: Final = "21:00:00"

# Ranges (spec §5.3)
MIN_BRIGHTNESS_PCT: Final = 1
MAX_BRIGHTNESS_PCT: Final = 100
MIN_KELVIN: Final = 1500
MAX_KELVIN: Final = 6500
MAX_OFFSET_MIN: Final = 180
MAX_TRANSITION_MIN: Final = 180

# Tuning (spec §6.4, §7.2): adjust against real hardware
TICK_SECONDS: Final = 30
STEP_FADE_SECONDS: Final = 2
SETTLE_SECONDS: Final = 10
BRIGHTNESS_TOLERANCE: Final = 5  # of 255
MIRED_TOLERANCE: Final = 10
EXPLICIT_CONTEXT_SECONDS: Final = 10
RECENT_CONTEXTS: Final = 5

# Persistence (spec §9)
STORAGE_VERSION: Final = 1
SAVE_DELAY_SECONDS: Final = 1
```

Create `custom_components/light_manager/models.py`:

```python
"""Frozen config models built from subentry data. Pure: no Home Assistant imports."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .const import (
    CONF_BRIGHTNESS_PCT,
    CONF_COLOR_TEMP_KELVIN,
    CONF_DAY,
    CONF_DAY_TARGET,
    CONF_LIGHT_OVERRIDES,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_NIGHT,
    CONF_NIGHT_TARGET,
    CONF_OFF_BEHAVIOR,
    CONF_OFFSET_MIN,
    CONF_TIME,
    CONF_TRANSITION_MIN,
    CONF_TYPE,
    TARGET_FIXED,
)


class Phase(StrEnum):
    """Where a group is in its daily cycle."""

    DAY = "day"
    TO_NIGHT = "to_night"
    NIGHT = "night"
    TO_DAY = "to_day"


RAMP_PHASES = frozenset({Phase.TO_NIGHT, Phase.TO_DAY})


@dataclass(frozen=True, slots=True)
class Setpoint:
    """A brightness/color-temperature pair."""

    brightness_pct: int
    color_temp_kelvin: int

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> Setpoint:
        return cls(int(data[CONF_BRIGHTNESS_PCT]), int(data[CONF_COLOR_TEMP_KELVIN]))


@dataclass(frozen=True, slots=True)
class TargetTime:
    """When a group must arrive at a setpoint: sun event + offset, or fixed."""

    type: str
    offset: dt.timedelta = dt.timedelta(0)
    time: dt.time | None = None

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> TargetTime:
        if data[CONF_TYPE] == TARGET_FIXED:
            return cls(TARGET_FIXED, time=dt.time.fromisoformat(data[CONF_TIME]))
        return cls(
            data[CONF_TYPE],
            offset=dt.timedelta(minutes=int(data.get(CONF_OFFSET_MIN, 0))),
        )


@dataclass(frozen=True, slots=True)
class LightOverride:
    """Per-light setpoint values; None means follow the group."""

    day_brightness_pct: int | None = None
    day_color_temp_kelvin: int | None = None
    night_brightness_pct: int | None = None
    night_color_temp_kelvin: int | None = None

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> LightOverride:
        return cls(
            **{
                key: int(data[key])
                for key in cls.__dataclass_fields__
                if data.get(key) is not None
            }
        )


@dataclass(frozen=True, slots=True)
class GroupConfig:
    """One light group's configuration (a `group` subentry)."""

    name: str
    lights: tuple[str, ...]
    day: Setpoint
    night: Setpoint
    day_target: TargetTime
    night_target: TargetTime
    transition: dt.timedelta
    off_behavior: str
    light_overrides: Mapping[str, LightOverride] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> GroupConfig:
        return cls(
            name=data[CONF_NAME],
            lights=tuple(data[CONF_LIGHTS]),
            day=Setpoint.from_data(data[CONF_DAY]),
            night=Setpoint.from_data(data[CONF_NIGHT]),
            day_target=TargetTime.from_data(data[CONF_DAY_TARGET]),
            night_target=TargetTime.from_data(data[CONF_NIGHT_TARGET]),
            transition=dt.timedelta(minutes=int(data[CONF_TRANSITION_MIN])),
            off_behavior=data[CONF_OFF_BEHAVIOR],
            light_overrides=MappingProxyType(
                {
                    entity_id: LightOverride.from_data(values)
                    for entity_id, values in data.get(CONF_LIGHT_OVERRIDES, {}).items()
                }
            ),
        )
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q`
Expected: `5 passed`.

- [ ] **Step 7: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: `… files already formatted` and `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .python-version uv.lock custom_components tests
git commit -m "Add project scaffold, constants and config models"
```

---

### Task 2: Schedule (target times, ramps, phases, holds)

**Files:**
- Create: `custom_components/light_manager/schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Consumes: `models.Phase`, `models.RAMP_PHASES`, `models.TargetTime`.
- Produces:
  - `type SunProvider = Callable[[dt.date, str], dt.datetime | None]`: event is `"sunrise"` or `"sunset"`; returns the UTC datetime, or `None` if the event doesn't happen that day.
  - `type Kind = Literal["day", "night"]`.
  - `PhaseInfo(phase: Phase, progress: float | None, window_start, target, next_day_target, next_night_target)`: the datetimes are UTC or `None`, and `progress` is 0..1 during a ramp.
  - `fixed_targets_valid(day: dt.time, night: dt.time, transition: dt.timedelta) -> bool`.
  - `Schedule(day_target: TargetTime, night_target: TargetTime, transition: timedelta, sun: SunProvider, tz: dt.tzinfo)` with methods:
    - `next_target(kind, after) -> datetime | None` (strictly after)
    - `window_start(kind, target) -> datetime`
    - `phase_at(now) -> PhaseInfo`
    - `hold_expiry(held: Phase, pressed_at) -> datetime | None`
    - `ramp_starts_between(start, end) -> list[datetime]` (start < s <= end)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_schedule.py`:

```python
"""Tests for schedule.py (pure; fake sun, US/Pacific)."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from custom_components.light_manager.models import Phase, TargetTime
from custom_components.light_manager.schedule import Schedule, fixed_targets_valid

PACIFIC = ZoneInfo("US/Pacific")
MIN30 = dt.timedelta(minutes=30)


def local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=PACIFIC)


def sept30(h: int, mi: int = 0, s: int = 0) -> dt.datetime:
    return local(2026, 9, 30, h, mi, s)


def fixed(hour: int, minute: int = 0) -> TargetTime:
    return TargetTime("fixed", time=dt.time(hour, minute))


def sun_target(offset_min: int = 0) -> TargetTime:
    return TargetTime("sun", offset=dt.timedelta(minutes=offset_min))


def fake_sun(missing=frozenset()):
    """Sunrise 06:50, sunset 18:40 local every day, except (date, event) in missing."""

    def sun(day: dt.date, event: str) -> dt.datetime | None:
        if (day, event) in missing:
            return None
        clock = dt.time(6, 50) if event == "sunrise" else dt.time(18, 40)
        return dt.datetime.combine(day, clock, PACIFIC).astimezone(dt.UTC)

    return sun


def no_sun(day: dt.date, event: str) -> None:
    return None


def fixed_schedule(transition: dt.timedelta = MIN30) -> Schedule:
    return Schedule(fixed(7), fixed(21), transition, fake_sun(), PACIFIC)


@pytest.mark.parametrize(
    ("now", "phase", "progress"),
    [
        (sept30(6, 0), Phase.NIGHT, None),
        (sept30(6, 30), Phase.TO_DAY, 0.0),
        (sept30(6, 45), Phase.TO_DAY, 0.5),
        (sept30(7, 0), Phase.DAY, None),
        (sept30(12, 0), Phase.DAY, None),
        (sept30(20, 30), Phase.TO_NIGHT, 0.0),
        (sept30(20, 40), Phase.TO_NIGHT, 1 / 3),
        (sept30(20, 59, 59), Phase.TO_NIGHT, 1799 / 1800),
        (sept30(21, 0), Phase.NIGHT, None),
        (sept30(23, 59), Phase.NIGHT, None),
    ],
)
def test_fixed_target_phases(now, phase, progress) -> None:
    info = fixed_schedule().phase_at(now)

    assert info.phase == phase
    if progress is None:
        assert info.progress is None
    else:
        assert info.progress == pytest.approx(progress)


def test_next_targets_reported() -> None:
    info = fixed_schedule().phase_at(sept30(12, 0))

    assert info.next_day_target == local(2026, 10, 1, 7, 0)
    assert info.next_night_target == sept30(21, 0)
    assert info.target == sept30(21, 0)
    assert info.window_start == sept30(20, 30)


def test_sun_targets_with_offsets() -> None:
    schedule = Schedule(sun_target(-15), sun_target(20), MIN30, fake_sun(), PACIFIC)

    assert schedule.phase_at(sept30(6, 4)).phase == Phase.NIGHT
    morning = schedule.phase_at(sept30(6, 20))
    assert morning.phase == Phase.TO_DAY
    assert morning.progress == pytest.approx(0.5)
    assert schedule.phase_at(sept30(6, 35)).phase == Phase.DAY
    evening = schedule.phase_at(sept30(18, 45))
    assert evening.phase == Phase.TO_NIGHT
    assert evening.progress == pytest.approx(0.5)
    assert schedule.phase_at(sept30(19, 0)).phase == Phase.NIGHT


def test_close_targets_shorten_the_ramp() -> None:
    # Night target 20 min after the day target: the to_night ramp can't start
    # before the day target, so it lasts 20 min instead of 30.
    schedule = Schedule(fixed(7), fixed(7, 20), MIN30, fake_sun(), PACIFIC)

    info = schedule.phase_at(sept30(7, 10))
    assert info.phase == Phase.TO_NIGHT
    assert info.window_start == sept30(7, 0)
    assert info.progress == pytest.approx(0.5)
    morning = schedule.phase_at(sept30(6, 45))
    assert morning.phase == Phase.TO_DAY
    assert morning.progress == pytest.approx(0.5)


def test_one_missing_sunset_keeps_day() -> None:
    sun = fake_sun(missing={(dt.date(2026, 9, 30), "sunset")})
    schedule = Schedule(sun_target(), sun_target(), MIN30, sun, PACIFIC)

    # No sunset on 9/30: day continues through the night and next morning
    # (no ramp back toward a day setpoint we're already at).
    assert schedule.phase_at(sept30(20, 0)).phase == Phase.DAY
    assert schedule.phase_at(local(2026, 10, 1, 6, 40)).phase == Phase.DAY
    evening = schedule.phase_at(local(2026, 10, 1, 18, 20))
    assert evening.phase == Phase.TO_NIGHT
    assert evening.progress == pytest.approx(1 / 3)


def test_sun_events_missing_for_forty_days() -> None:
    missing = {
        (dt.date(2026, 10, 1) + dt.timedelta(days=i), event)
        for i in range(40)
        for event in ("sunrise", "sunset")
    }
    schedule = Schedule(sun_target(), sun_target(), MIN30, fake_sun(missing), PACIFIC)

    info = schedule.phase_at(local(2026, 10, 1, 12, 0))

    assert info.phase == Phase.NIGHT
    assert info.next_day_target == local(2026, 11, 10, 6, 50)
    assert info.next_night_target == local(2026, 11, 10, 18, 40)


def test_no_sun_events_at_all() -> None:
    schedule = Schedule(sun_target(), sun_target(), MIN30, no_sun, PACIFIC)

    info = schedule.phase_at(sept30(12, 0))

    assert info.phase == Phase.DAY
    assert info.progress is None
    assert info.target is None
    assert schedule.hold_expiry(Phase.NIGHT, sept30(12, 0)) is None
    assert schedule.ramp_starts_between(sept30(0, 0), sept30(23, 0)) == []


def test_transition_zero_switches_instantly() -> None:
    schedule = fixed_schedule(dt.timedelta(0))

    assert schedule.phase_at(sept30(20, 59, 59)).phase == Phase.DAY
    assert schedule.phase_at(sept30(21, 0)).phase == Phase.NIGHT
    assert schedule.phase_at(sept30(6, 59, 59)).phase == Phase.NIGHT
    assert schedule.phase_at(sept30(7, 0)).phase == Phase.DAY


@pytest.mark.parametrize(
    ("held", "pressed_at", "expiry"),
    [
        (Phase.NIGHT, sept30(12, 0), local(2026, 10, 1, 6, 30)),
        (Phase.DAY, sept30(23, 0), local(2026, 10, 1, 20, 30)),
        # Pressed inside the ramp it opposes: wait for tomorrow's.
        (Phase.NIGHT, sept30(6, 45), local(2026, 10, 1, 6, 30)),
        (Phase.DAY, sept30(20, 40), local(2026, 10, 1, 20, 30)),
        # Night now mid to_night ramp: held until the next morning ramp.
        (Phase.NIGHT, sept30(20, 40), local(2026, 10, 1, 6, 30)),
        (Phase.DAY, sept30(6, 45), sept30(20, 30)),
    ],
)
def test_hold_expiry(held, pressed_at, expiry) -> None:
    assert fixed_schedule().hold_expiry(held, pressed_at) == expiry


def test_ramp_starts_between_is_exclusive_inclusive() -> None:
    schedule = fixed_schedule()

    assert schedule.ramp_starts_between(sept30(6, 0), sept30(21, 0)) == [
        sept30(6, 30),
        sept30(20, 30),
    ]
    assert schedule.ramp_starts_between(sept30(6, 30), sept30(20, 30)) == [
        sept30(20, 30)
    ]
    assert schedule.ramp_starts_between(sept30(7, 0), sept30(20, 0)) == []


@pytest.mark.parametrize(
    ("day", "night", "minutes", "valid"),
    [
        (dt.time(7), dt.time(21), 30, True),
        (dt.time(7), dt.time(7), 0, False),
        (dt.time(7), dt.time(7, 20), 30, False),
        (dt.time(7), dt.time(7, 20), 20, True),
        (dt.time(23, 50), dt.time(0, 10), 20, True),
        (dt.time(23, 50), dt.time(0, 10), 21, False),
        (dt.time(7), dt.time(19), 720, True),
        (dt.time(7), dt.time(19), 721, False),
    ],
)
def test_fixed_targets_valid(day, night, minutes, valid) -> None:
    assert fixed_targets_valid(day, night, dt.timedelta(minutes=minutes)) is valid


def test_fixed_targets_follow_wall_clock_across_dst() -> None:
    # US DST ends 2026-11-01 02:00 PDT -> 01:00 PST.
    schedule = fixed_schedule()

    before = schedule.next_target("day", local(2026, 10, 30, 12, 0))
    after = schedule.next_target("day", local(2026, 10, 31, 12, 0))

    assert before == dt.datetime(2026, 10, 31, 14, 0, tzinfo=dt.UTC)  # 07:00 PDT
    assert after == dt.datetime(2026, 11, 1, 15, 0, tzinfo=dt.UTC)  # 07:00 PST
    ramp = schedule.phase_at(local(2026, 11, 1, 6, 45))
    assert ramp.phase == Phase.TO_DAY
    assert ramp.progress == pytest.approx(0.5)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_schedule.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'custom_components.light_manager.schedule'`.

- [ ] **Step 3: Implement the schedule**

Create `custom_components/light_manager/schedule.py`:

```python
"""Schedule math: phases, ramp windows and hold expiry. Pure: no HA imports.

All datetimes are timezone-aware. Sun times come from an injected callable so
tests can use fixed sunrise/sunset times.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .const import TARGET_FIXED
from .models import Phase, TargetTime

type SunProvider = Callable[[dt.date, str], dt.datetime | None]
"""(local date, "sunrise" | "sunset") -> aware datetime, or None if no event."""

type Kind = Literal["day", "night"]

_SUN_EVENT: dict[Kind, str] = {"day": "sunrise", "night": "sunset"}
_OPPOSITE: dict[Kind, Kind] = {"day": "night", "night": "day"}
_RAMP: dict[Kind, Phase] = {"day": Phase.TO_DAY, "night": Phase.TO_NIGHT}
_PLATEAU: dict[Kind, Phase] = {"day": Phase.DAY, "night": Phase.NIGHT}
# Look this many days ahead/back for a target: first a short search, then a
# year (polar regions can go months without a sunrise or sunset).
_SEARCH_DAYS = (2, 370)


@dataclass(frozen=True, slots=True)
class PhaseInfo:
    """The schedule's answer for one moment."""

    phase: Phase
    progress: float | None  # 0..1 during a ramp, else None
    window_start: dt.datetime | None  # start of the upcoming/current ramp
    target: dt.datetime | None  # the next target (end of that ramp)
    next_day_target: dt.datetime | None
    next_night_target: dt.datetime | None


def fixed_targets_valid(day: dt.time, night: dt.time, transition: dt.timedelta) -> bool:
    """Spec §5.3: fixed targets differ and are at least a transition apart."""
    day_s = day.hour * 3600 + day.minute * 60 + day.second
    night_s = night.hour * 3600 + night.minute * 60 + night.second
    gap = abs(day_s - night_s)
    if gap == 0:
        return False
    return min(gap, 86400 - gap) >= transition.total_seconds()


def _earlier_kind(day: dt.datetime | None, night: dt.datetime | None) -> Kind:
    """Which of two optional moments comes first (day wins ties; None is last)."""
    if night is None or (day is not None and day <= night):
        return "day"
    return "night"


class Schedule:
    """Computes target times, ramp windows and phases for one group."""

    def __init__(
        self,
        day_target: TargetTime,
        night_target: TargetTime,
        transition: dt.timedelta,
        sun: SunProvider,
        tz: dt.tzinfo,
    ) -> None:
        self._targets: dict[Kind, TargetTime] = {
            "day": day_target,
            "night": night_target,
        }
        self._transition = transition
        self._sun = sun
        self._tz = tz

    def _on_date(self, kind: Kind, day: dt.date) -> dt.datetime | None:
        """The kind's target for a local date, or None if the sun event is missing."""
        target = self._targets[kind]
        if target.type == TARGET_FIXED:
            assert target.time is not None
            return dt.datetime.combine(day, target.time, self._tz).astimezone(dt.UTC)
        event = self._sun(day, _SUN_EVENT[kind])
        return None if event is None else event + target.offset

    def _between(
        self, kind: Kind, start: dt.datetime, end: dt.datetime
    ) -> list[dt.datetime]:
        """All targets of a kind with start <= t <= end, ascending."""
        day = start.astimezone(self._tz).date() - dt.timedelta(days=1)
        last = end.astimezone(self._tz).date() + dt.timedelta(days=1)
        found: list[dt.datetime] = []
        while day <= last:
            moment = self._on_date(kind, day)
            if moment is not None and start <= moment <= end:
                found.append(moment)
            day += dt.timedelta(days=1)
        return sorted(found)

    def next_target(self, kind: Kind, after: dt.datetime) -> dt.datetime | None:
        """The first target of a kind strictly after a moment."""
        for days in _SEARCH_DAYS:
            end = after + dt.timedelta(days=days)
            found = [t for t in self._between(kind, after, end) if t > after]
            if found:
                return found[0]
        return None

    def _last_target(
        self, kind: Kind, moment: dt.datetime, *, inclusive: bool
    ) -> dt.datetime | None:
        """The latest target of a kind before (or at, if inclusive) a moment."""
        for days in _SEARCH_DAYS:
            start = moment - dt.timedelta(days=days)
            found = [
                t
                for t in self._between(kind, start, moment)
                if t < moment or (inclusive and t == moment)
            ]
            if found:
                return found[-1]
        return None

    def window_start(self, kind: Kind, target: dt.datetime) -> dt.datetime:
        """Spec §6.2: max(target - transition, previous opposite target)."""
        start = target - self._transition
        previous = self._last_target(_OPPOSITE[kind], target, inclusive=False)
        if previous is not None and previous > start:
            start = previous
        return start

    def phase_at(self, now: dt.datetime) -> PhaseInfo:
        """Spec §6.2: the phase from the clock alone."""
        next_day = self.next_target("day", now)
        next_night = self.next_target("night", now)
        if next_day is None and next_night is None:
            return PhaseInfo(Phase.DAY, None, None, None, None, None)
        kind = _earlier_kind(next_day, next_night)
        target = next_day if kind == "day" else next_night
        assert target is not None

        # Targets normally alternate. If the latest one was the same kind (a
        # sun event didn't occur), we already arrived: stay, with no ramp.
        last_day = self._last_target("day", now, inclusive=True)
        last_night = self._last_target("night", now, inclusive=True)
        if last_day is not None or last_night is not None:
            if last_night is None or (last_day is not None and last_day > last_night):
                last_kind = "day"
            else:
                last_kind = "night"
            if last_kind == kind:
                return PhaseInfo(
                    _PLATEAU[kind], None, None, target, next_day, next_night
                )

        start = self.window_start(kind, target)
        if start <= now < target:
            progress = (now - start) / (target - start)
            return PhaseInfo(_RAMP[kind], progress, start, target, next_day, next_night)
        return PhaseInfo(
            _PLATEAU[_OPPOSITE[kind]], None, start, target, next_day, next_night
        )

    def hold_expiry(self, held: Phase, pressed_at: dt.datetime) -> dt.datetime | None:
        """Spec §6.5: the first opposite ramp start strictly after the press.

        Night now waits for the next to_day ramp; Day now for the next to_night.
        """
        kind: Kind = "day" if held == Phase.NIGHT else "night"
        moment = pressed_at
        for _ in range(3):
            target = self.next_target(kind, moment)
            if target is None:
                return None
            start = self.window_start(kind, target)
            if start > pressed_at:
                return start
            moment = target
        return None

    def ramp_starts_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[dt.datetime]:
        """Every ramp window start s (either kind) with start < s <= end."""
        found: list[dt.datetime] = []
        for kind in ("day", "night"):
            for target in self._between(kind, start, end + self._transition):
                window = self.window_start(kind, target)
                if start < window <= end:
                    found.append(window)
        return sorted(found)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: `38 passed`.

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add custom_components/light_manager/schedule.py tests/test_schedule.py
git commit -m "Add schedule: target times, ramp windows, phases and holds"
```

---

### Task 3: Curve (interpolation and per-light commands)

**Files:**
- Create: `custom_components/light_manager/curve.py`
- Test: `tests/test_curve.py`

**Interfaces:**
- Consumes: `models.Phase`, `models.Setpoint`, `models.LightOverride`; `const.MIN_KELVIN`/`MAX_KELVIN`.
- Produces:
  - `LightCapabilities(brightness: bool, color_temp: bool, emulated_color_temp: bool, min_kelvin: int | None = None, max_kelvin: int | None = None)` with an `.any_color_temp` property.
  - `capabilities_from_attributes(attrs: Mapping[str, Any]) -> LightCapabilities`.
  - `LightCommand(brightness: int, color_temp_kelvin: int | None = None)` with `.service_data() -> dict[str, int]`.
  - `effective_setpoints(day, night, override: LightOverride | None) -> tuple[Setpoint, Setpoint]`.
  - `interpolate(start: Setpoint, end: Setpoint, progress: float) -> tuple[float, float]`: brightness % is linear; color temp is linear in mireds.
  - `setpoint_at(day, night, phase: Phase, progress: float | None) -> tuple[float, float]`.
  - `light_command(pct: float, kelvin: float, caps: LightCapabilities) -> LightCommand | None`: `None` means "never command this light" (on/off only).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_curve.py`:

```python
"""Tests for curve.py."""

import pytest

from custom_components.light_manager.curve import (
    LightCapabilities,
    LightCommand,
    capabilities_from_attributes,
    effective_setpoints,
    interpolate,
    light_command,
    setpoint_at,
)
from custom_components.light_manager.models import LightOverride, Phase, Setpoint

DAY = Setpoint(100, 4000)
NIGHT = Setpoint(20, 2200)
CT_CAPS = LightCapabilities(
    brightness=True,
    color_temp=True,
    emulated_color_temp=False,
    min_kelvin=2000,
    max_kelvin=6500,
)
DIMMER_CAPS = LightCapabilities(
    brightness=True, color_temp=False, emulated_color_temp=False
)


@pytest.mark.parametrize(
    ("minute", "pct", "kelvin", "brightness"),
    [
        (0, 100, 4000, 255),
        (10, 73.33, 3143, 187),
        (20, 46.67, 2588, 119),
        (30, 20, 2200, 51),
    ],
)
def test_spec_ramp_table(minute, pct, kelvin, brightness) -> None:
    got_pct, got_kelvin = setpoint_at(DAY, NIGHT, Phase.TO_NIGHT, minute / 30)

    assert got_pct == pytest.approx(pct, abs=0.01)
    assert round(got_kelvin) == kelvin
    assert light_command(got_pct, got_kelvin, CT_CAPS) == LightCommand(
        brightness, kelvin
    )


def test_to_day_ramps_from_night_to_day() -> None:
    pct, kelvin = setpoint_at(DAY, NIGHT, Phase.TO_DAY, 2 / 3)

    assert pct == pytest.approx(73.33, abs=0.01)
    assert round(kelvin) == 3143


@pytest.mark.parametrize(
    ("phase", "expected"),
    [(Phase.DAY, (100.0, 4000.0)), (Phase.NIGHT, (20.0, 2200.0))],
)
def test_plateaus_ignore_progress(phase, expected) -> None:
    assert setpoint_at(DAY, NIGHT, phase, None) == expected


def test_interpolate_endpoints_are_exact() -> None:
    assert interpolate(DAY, NIGHT, 0.0) == pytest.approx((100, 4000))
    assert interpolate(DAY, NIGHT, 1.0) == pytest.approx((20, 2200))


def test_partial_override_keeps_other_group_values() -> None:
    day, night = effective_setpoints(DAY, NIGHT, LightOverride(night_brightness_pct=5))

    assert day == DAY
    assert night == Setpoint(5, 2200)


def test_full_override_replaces_everything() -> None:
    override = LightOverride(
        day_brightness_pct=80,
        day_color_temp_kelvin=3500,
        night_brightness_pct=1,
        night_color_temp_kelvin=1800,
    )

    assert effective_setpoints(DAY, NIGHT, override) == (
        Setpoint(80, 3500),
        Setpoint(1, 1800),
    )


def test_no_override_returns_group_setpoints() -> None:
    assert effective_setpoints(DAY, NIGHT, None) == (DAY, NIGHT)


def test_kelvin_clamped_to_light_range() -> None:
    narrow = LightCapabilities(
        brightness=True,
        color_temp=True,
        emulated_color_temp=False,
        min_kelvin=2700,
        max_kelvin=3000,
    )

    assert light_command(20, 2200, narrow) == LightCommand(51, 2700)
    assert light_command(100, 4000, narrow) == LightCommand(255, 3000)


def test_brightness_only_light_gets_no_color_temp() -> None:
    command = light_command(20, 2200, DIMMER_CAPS)

    assert command == LightCommand(51)
    assert command.service_data() == {"brightness": 51}


def test_tiny_brightness_never_rounds_to_off() -> None:
    assert light_command(0.1, 2200, DIMMER_CAPS) == LightCommand(1)


def test_emulated_color_temp_is_sent_unclamped() -> None:
    caps = capabilities_from_attributes({"supported_color_modes": ["hs"]})

    assert caps.emulated_color_temp
    assert caps.any_color_temp
    assert light_command(20, 1600.4, caps) == LightCommand(51, 1600)


@pytest.mark.parametrize("modes", [["onoff"], [], None])
def test_on_off_only_lights_are_never_commanded(modes) -> None:
    caps = capabilities_from_attributes({"supported_color_modes": modes})

    assert light_command(50, 3000, caps) is None


def test_capabilities_native_color_temp() -> None:
    caps = capabilities_from_attributes(
        {
            "supported_color_modes": ["color_temp", "hs"],
            "min_color_temp_kelvin": 2000,
            "max_color_temp_kelvin": 6535,
        }
    )

    assert caps == LightCapabilities(
        brightness=True,
        color_temp=True,
        emulated_color_temp=False,
        min_kelvin=2000,
        max_kelvin=6535,
    )


def test_capabilities_brightness_only() -> None:
    caps = capabilities_from_attributes({"supported_color_modes": ["brightness"]})

    assert caps == DIMMER_CAPS
    assert not caps.any_color_temp


def test_service_data_with_color_temp() -> None:
    assert LightCommand(187, 3143).service_data() == {
        "brightness": 187,
        "color_temp_kelvin": 3143,
    }
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_curve.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'custom_components.light_manager.curve'`.

- [ ] **Step 3: Implement the curve**

Create `custom_components/light_manager/curve.py`:

```python
"""Per-light targets: setpoints, interpolation and capability limits.

Pure: no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import LightOverride, Phase, Setpoint

_NOT_DIMMABLE = frozenset({"onoff", "unknown"})
_COLOR_MODES = frozenset({"hs", "xy", "rgb", "rgbw", "rgbww"})


@dataclass(frozen=True, slots=True)
class LightCapabilities:
    """What a light can do, read from its state attributes."""

    brightness: bool
    color_temp: bool  # native color_temp mode
    emulated_color_temp: bool  # color modes only; HA converts color_temp_kelvin
    min_kelvin: int | None = None
    max_kelvin: int | None = None

    @property
    def any_color_temp(self) -> bool:
        return self.color_temp or self.emulated_color_temp


def capabilities_from_attributes(attrs: Mapping[str, Any]) -> LightCapabilities:
    """Spec §7.5: capabilities from supported_color_modes and the Kelvin range."""
    modes = set(attrs.get("supported_color_modes") or ())
    color_temp = "color_temp" in modes
    return LightCapabilities(
        brightness=bool(modes - _NOT_DIMMABLE),
        color_temp=color_temp,
        emulated_color_temp=not color_temp and bool(modes & _COLOR_MODES),
        min_kelvin=attrs.get("min_color_temp_kelvin") if color_temp else None,
        max_kelvin=attrs.get("max_color_temp_kelvin") if color_temp else None,
    )


@dataclass(frozen=True, slots=True)
class LightCommand:
    """Values for one light.turn_on call (transition is added by the caller)."""

    brightness: int  # 1-255
    color_temp_kelvin: int | None = None

    def service_data(self) -> dict[str, int]:
        data = {"brightness": self.brightness}
        if self.color_temp_kelvin is not None:
            data["color_temp_kelvin"] = self.color_temp_kelvin
        return data


def effective_setpoints(
    day: Setpoint, night: Setpoint, override: LightOverride | None
) -> tuple[Setpoint, Setpoint]:
    """Spec §6.3 step 1: each value is the light override if set, else the group's."""
    if override is None:
        return day, night

    def pick(value: int | None, default: int) -> int:
        return default if value is None else value

    return (
        Setpoint(
            pick(override.day_brightness_pct, day.brightness_pct),
            pick(override.day_color_temp_kelvin, day.color_temp_kelvin),
        ),
        Setpoint(
            pick(override.night_brightness_pct, night.brightness_pct),
            pick(override.night_color_temp_kelvin, night.color_temp_kelvin),
        ),
    )


def interpolate(start: Setpoint, end: Setpoint, progress: float) -> tuple[float, float]:
    """Spec §6.3 step 2: brightness linear in %, color temp linear in mireds."""
    pct = start.brightness_pct + (end.brightness_pct - start.brightness_pct) * progress
    start_mired = 1e6 / start.color_temp_kelvin
    end_mired = 1e6 / end.color_temp_kelvin
    mired = start_mired + (end_mired - start_mired) * progress
    return pct, 1e6 / mired


def setpoint_at(
    day: Setpoint, night: Setpoint, phase: Phase, progress: float | None
) -> tuple[float, float]:
    """(brightness %, Kelvin) for a phase; progress is used only during ramps."""
    match phase:
        case Phase.DAY:
            return float(day.brightness_pct), float(day.color_temp_kelvin)
        case Phase.NIGHT:
            return float(night.brightness_pct), float(night.color_temp_kelvin)
        case Phase.TO_NIGHT:
            return interpolate(day, night, progress or 0.0)
        case Phase.TO_DAY:
            return interpolate(night, day, progress or 0.0)


def light_command(
    pct: float, kelvin: float, caps: LightCapabilities
) -> LightCommand | None:
    """Spec §6.3 step 3 / §7.5: limit to what the light can do. None = never command."""
    if not caps.brightness:
        return None
    brightness = max(1, round(pct * 255 / 100))
    if caps.color_temp:
        value = round(kelvin)
        if caps.min_kelvin is not None:
            value = max(caps.min_kelvin, value)
        if caps.max_kelvin is not None:
            value = min(caps.max_kelvin, value)
        return LightCommand(brightness, value)
    if caps.emulated_color_temp:
        return LightCommand(brightness, round(kelvin))
    return LightCommand(brightness)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: `59 passed`.

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add custom_components/light_manager/curve.py tests/test_curve.py
git commit -m "Add curve: setpoint interpolation and per-light commands"
```

---

### Task 4: Light tracker (manual-override detection)

**Files:**
- Create: `custom_components/light_manager/light_tracker.py`
- Test: `tests/test_light_tracker.py`

**Interfaces:**
- Consumes:
  - `curve.LightCommand`, `curve.LightCapabilities`
  - `const.SETTLE_SECONDS`, `BRIGHTNESS_TOLERANCE`, `MIRED_TOLERANCE`, `RECENT_CONTEXTS`, `OFF_RETURN_TO_AUTO`
- Produces:
  - `EXPLICIT_KEYS` and `is_explicit_turn_on(service: str, service_data: Mapping) -> bool`.
  - `Mode(StrEnum)` with `AUTO` and `OVERRIDDEN`.
  - `Reading(brightness: int | None, color_temp_kelvin: int | None, color_mode: str | None)` with `.from_attributes(attrs)`.
  - `Classification(manual: bool, reason: str)`.
  - `LightTracker(entity_id)` dataclass:
    - Fields: `mode`, `overridden_at`, `expected: LightCommand | None`, `pre_command`, `sent_at`, `fade_s`.
    - Methods:
      - `should_send(command) -> bool`
      - `begin_command(command, context_id, now, fade_s, current: Reading) -> _Sent`
      - `command_failed(previous: _Sent)`
      - `is_own_context(context_id) -> bool`
      - `mark_overridden(now)`
      - `reset_auto()`: also clears `expected`, so the same target is resent.
      - `on_turned_off(off_behavior) -> bool`: returns True if the mode changed.
      - `on_unavailable()`
      - `classify(old: Reading, new: Reading, context_id, now, caps) -> Classification`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_light_tracker.py`:

```python
"""Tests for light_tracker.py: Z-Wave timing scenarios and mode changes."""

import datetime as dt

import pytest

from custom_components.light_manager.curve import LightCapabilities, LightCommand
from custom_components.light_manager.light_tracker import (
    LightTracker,
    Mode,
    Reading,
    is_explicit_turn_on,
)

T0 = dt.datetime(2026, 9, 30, 20, 40, tzinfo=dt.UTC)
DIMMER = LightCapabilities(brightness=True, color_temp=False, emulated_color_temp=False)
CT = LightCapabilities(
    brightness=True,
    color_temp=True,
    emulated_color_temp=False,
    min_kelvin=2000,
    max_kelvin=6500,
)
COLOR_ONLY = LightCapabilities(
    brightness=True, color_temp=False, emulated_color_temp=True
)


def at(seconds: float) -> dt.datetime:
    return T0 + dt.timedelta(seconds=seconds)


def dim(brightness: int | None) -> Reading:
    return Reading(brightness, None, "brightness" if brightness else None)


def ct(brightness: int, kelvin: int | None, mode: str = "color_temp") -> Reading:
    return Reading(brightness, kelvin, mode)


def sent_dimmer(pre: int, target: int, fade: float = 2) -> LightTracker:
    """A dimmer we just commanded from `pre` to `target` at T0 with context c1."""
    tracker = LightTracker("light.dimmer")
    tracker.begin_command(LightCommand(target), "c1", T0, fade, dim(pre))
    return tracker


# --- Z-Wave scenarios (spec §11) ---


def test_late_report_with_fresh_context_matching_target_is_ours() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    result = tracker.classify(dim(120), dim(51), "zwave-poll", at(30), DIMMER)

    assert not result.manual
    assert "rule 2" in result.reason


def test_mid_fade_reports_are_ours() -> None:
    tracker = sent_dimmer(pre=255, target=51)

    first = tracker.classify(dim(255), dim(180), "zwave-1", at(1), DIMMER)
    second = tracker.classify(dim(180), dim(90), "zwave-2", at(2.5), DIMMER)

    assert not first.manual
    assert not second.manual
    assert "rule 3" in second.reason


def test_dimmer_settling_above_requested_minimum_is_ours() -> None:
    # Asked for 5% (13/255); the dimmer stops at 10% (26/255) within the window.
    tracker = sent_dimmer(pre=51, target=13)

    result = tracker.classify(dim(51), dim(26), "zwave-1", at(8), DIMMER)

    assert not result.manual
    assert "rule 3" in result.reason


def test_user_sets_100_percent_is_manual() -> None:
    tracker = sent_dimmer(pre=120, target=115)

    result = tracker.classify(dim(115), dim(255), "user", at(5), DIMMER)

    assert result.manual
    assert result.reason == "brightness 255/255"


def test_nudge_within_tolerance_is_ours_even_later() -> None:
    tracker = sent_dimmer(pre=60, target=51)

    result = tracker.classify(dim(51), dim(56), "user", at(600), DIMMER)

    assert not result.manual


def test_nudge_within_settle_band_only_counts_inside_the_window() -> None:
    tracker = sent_dimmer(pre=70, target=51)

    inside = tracker.classify(dim(51), dim(65), "zwave", at(11.9), DIMMER)
    outside = tracker.classify(dim(51), dim(65), "zwave", at(12.1), DIMMER)

    assert not inside.manual
    assert outside.manual


def test_our_context_explains_anything() -> None:
    tracker = sent_dimmer(pre=255, target=51)

    result = tracker.classify(dim(255), dim(200), "c1", at(300), DIMMER)

    assert result == (False, "rule 1: our context")


def test_change_with_nothing_sent_is_manual() -> None:
    tracker = LightTracker("light.dimmer")

    assert tracker.classify(dim(100), dim(150), "user", at(0), DIMMER).manual


def test_brightness_none_while_on_is_not_a_change() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    assert not tracker.classify(dim(51), dim(None), "zwave", at(60), DIMMER).manual
    assert not tracker.classify(dim(None), dim(51), "zwave", at(61), DIMMER).manual


def test_unchanged_values_are_not_a_change() -> None:
    tracker = LightTracker("light.dimmer")

    result = tracker.classify(dim(100), dim(100), "user", at(0), DIMMER)

    assert result == (False, "no tracked change")


# --- Color temperature ---


def sent_ct(pre: Reading, command: LightCommand) -> LightTracker:
    tracker = LightTracker("light.lamp")
    tracker.begin_command(command, "c1", T0, 2, pre)
    return tracker


def test_color_temp_within_mired_tolerance_is_ours() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    # 2600 K is ~1.8 mireds from 2588 K.
    result = tracker.classify(ct(187, 3143), ct(119, 2600), "zwave", at(60), CT)

    assert not result.manual


def test_user_color_temp_change_is_manual() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    result = tracker.classify(ct(119, 2588), ct(119, 4000), "user", at(60), CT)

    assert result == (True, "color_temp 4000 K")


def test_switch_to_color_mode_is_manual_even_during_settle() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    result = tracker.classify(
        ct(119, 2588), ct(119, None, mode="hs"), "user", at(1), CT
    )

    assert result.manual
    assert result.reason == "color mode -> hs"


def test_color_mode_change_with_our_context_is_ours() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    result = tracker.classify(ct(119, 2588), ct(119, None, mode="hs"), "c1", at(1), CT)

    assert not result.manual


def test_emulated_color_temp_light_only_watches_brightness() -> None:
    tracker = LightTracker("light.strip")
    tracker.begin_command(LightCommand(51, 2200), "c1", T0, 2, ct(51, 2200, "hs"))

    result = tracker.classify(
        ct(51, 2200, "hs"), ct(51, 6000, "hs"), "user", at(60), COLOR_ONLY
    )

    assert not result.manual


# --- Sending and modes ---


def test_should_send_only_when_auto_and_different() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    assert not tracker.should_send(LightCommand(51))
    assert tracker.should_send(LightCommand(52))
    tracker.mark_overridden(at(5))
    assert not tracker.should_send(LightCommand(52))
    assert tracker.mode is Mode.OVERRIDDEN
    assert tracker.overridden_at == at(5)


def test_reset_auto_forces_resend_of_same_target() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    tracker.mark_overridden(at(5))

    tracker.reset_auto()

    assert tracker.mode is Mode.AUTO
    assert tracker.overridden_at is None
    assert tracker.should_send(LightCommand(51))


def test_failed_command_is_rolled_back_so_it_retries() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    previous = tracker.begin_command(LightCommand(40), "c2", at(30), 2, dim(51))
    tracker.command_failed(previous)

    assert tracker.expected == LightCommand(51)
    assert tracker.sent_at == T0
    assert tracker.should_send(LightCommand(40))


def test_own_contexts_are_remembered_up_to_five() -> None:
    tracker = LightTracker("light.dimmer")
    for i in range(6):
        tracker.begin_command(LightCommand(i + 1), f"c{i}", at(i), 2, dim(1))

    assert not tracker.is_own_context("c0")
    assert all(tracker.is_own_context(f"c{i}") for i in range(1, 6))
    assert not tracker.is_own_context(None)


@pytest.mark.parametrize(
    ("behavior", "mode_after", "changed"),
    [
        ("return_to_auto", Mode.AUTO, True),
        ("stay_overridden", Mode.OVERRIDDEN, False),
    ],
)
def test_turned_off_with_each_off_behavior(behavior, mode_after, changed) -> None:
    tracker = sent_dimmer(pre=120, target=51)
    tracker.mark_overridden(at(5))

    assert tracker.on_turned_off(behavior) is changed
    assert tracker.mode is mode_after
    assert tracker.expected is None


def test_turned_off_while_auto_reports_no_mode_change() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    assert tracker.on_turned_off("return_to_auto") is False
    assert tracker.expected is None


def test_unavailable_round_trip_keeps_mode_and_forces_resend() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    tracker.mark_overridden(at(5))

    tracker.on_unavailable()

    assert tracker.mode is Mode.OVERRIDDEN
    assert tracker.expected is None


# --- Explicit turn-on detection (spec §7.4) ---


@pytest.mark.parametrize(
    ("service", "data", "explicit"),
    [
        ("turn_on", {"entity_id": "light.lamp", "brightness_pct": 40}, True),
        ("turn_on", {"color_temp_kelvin": 2700}, True),
        ("toggle", {"color_name": "red"}, True),
        ("turn_on", {"profile": "relax"}, True),
        ("turn_on", {"brightness_step_pct": -10}, True),
        ("turn_on", {"entity_id": "light.lamp"}, False),
        ("turn_on", {"transition": 3}, False),
        ("turn_off", {"brightness": 10}, False),
    ],
)
def test_is_explicit_turn_on(service, data, explicit) -> None:
    assert is_explicit_turn_on(service, data) is explicit


def test_reading_from_attributes() -> None:
    attrs = {"brightness": 51, "color_temp_kelvin": 2200, "color_mode": "color_temp"}

    assert Reading.from_attributes(attrs) == Reading(51, 2200, "color_temp")
    assert Reading.from_attributes({}) == Reading(None, None, None)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_light_tracker.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'custom_components.light_manager.light_tracker'`.

- [ ] **Step 3: Implement the tracker**

Create `custom_components/light_manager/light_tracker.py`:

```python
"""Per-light AUTO/OVERRIDDEN state machine and report classification (spec §7).

Pure: no Home Assistant imports. The runtime feeds it readings, context IDs and
times, and acts on its answers.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, NamedTuple

from .const import (
    BRIGHTNESS_TOLERANCE,
    MIRED_TOLERANCE,
    OFF_RETURN_TO_AUTO,
    RECENT_CONTEXTS,
    SETTLE_SECONDS,
)
from .curve import LightCapabilities, LightCommand

# Spec §7.4: service data keys that make a turn-on "explicit".
EXPLICIT_KEYS = frozenset(
    {
        "brightness",
        "brightness_pct",
        "brightness_step",
        "brightness_step_pct",
        "color_temp_kelvin",
        "hs_color",
        "xy_color",
        "rgb_color",
        "rgbw_color",
        "rgbww_color",
        "color_name",
        "white",
        "profile",
    }
)
_COLOR_MODES = frozenset({"hs", "xy", "rgb", "rgbw", "rgbww"})


def is_explicit_turn_on(service: str, service_data: Mapping[str, Any]) -> bool:
    """A light.turn_on/toggle call that sets brightness, color or a profile."""
    return service in ("turn_on", "toggle") and not EXPLICIT_KEYS.isdisjoint(
        service_data
    )


class Mode(StrEnum):
    AUTO = "auto"
    OVERRIDDEN = "overridden"


@dataclass(frozen=True, slots=True)
class Reading:
    """The attributes of one light state that classification looks at."""

    brightness: int | None
    color_temp_kelvin: int | None
    color_mode: str | None

    @classmethod
    def from_attributes(cls, attrs: Mapping[str, Any]) -> Reading:
        return cls(
            attrs.get("brightness"),
            attrs.get("color_temp_kelvin"),
            attrs.get("color_mode"),
        )


class Classification(NamedTuple):
    manual: bool
    reason: str


@dataclass(frozen=True, slots=True)
class _Sent:
    """Snapshot of the command fields, to roll back a failed send."""

    expected: LightCommand | None
    pre_command: Reading | None
    sent_at: dt.datetime | None
    fade_s: float


def _mired(kelvin: float) -> float:
    return 1e6 / kelvin


@dataclass
class LightTracker:
    """One member light's automation state (spec §7.1)."""

    entity_id: str
    mode: Mode = Mode.AUTO
    overridden_at: dt.datetime | None = None
    expected: LightCommand | None = None  # last command sent
    pre_command: Reading | None = None  # reading just before that command
    sent_at: dt.datetime | None = None
    fade_s: float = 0
    _contexts: deque[str] = field(default_factory=lambda: deque(maxlen=RECENT_CONTEXTS))

    def should_send(self, command: LightCommand) -> bool:
        """AUTO lights get a command unless it equals the last one sent."""
        return self.mode is Mode.AUTO and command != self.expected

    def begin_command(
        self,
        command: LightCommand,
        context_id: str,
        now: dt.datetime,
        fade_s: float,
        current: Reading,
    ) -> _Sent:
        """Record a command about to be sent; returns a snapshot for rollback."""
        previous = _Sent(self.expected, self.pre_command, self.sent_at, self.fade_s)
        self.expected = command
        self.pre_command = current
        self.sent_at = now
        self.fade_s = fade_s
        self._contexts.append(context_id)
        return previous

    def command_failed(self, previous: _Sent) -> None:
        """Spec §10: a failed send leaves expected as it was, so it's retried."""
        self.expected = previous.expected
        self.pre_command = previous.pre_command
        self.sent_at = previous.sent_at
        self.fade_s = previous.fade_s

    def is_own_context(self, context_id: str | None) -> bool:
        return context_id is not None and context_id in self._contexts

    def mark_overridden(self, now: dt.datetime) -> None:
        self.mode = Mode.OVERRIDDEN
        self.overridden_at = now

    def reset_auto(self) -> None:
        """Back to AUTO. Forgets the last command so the target is always resent."""
        self.mode = Mode.AUTO
        self.overridden_at = None
        self.expected = None

    def on_turned_off(self, off_behavior: str) -> bool:
        """Spec §7.3. Returns True if the mode changed."""
        self.expected = None
        if self.mode is Mode.OVERRIDDEN and off_behavior == OFF_RETURN_TO_AUTO:
            self.mode = Mode.AUTO
            self.overridden_at = None
            return True
        return False

    def on_unavailable(self) -> None:
        """The light's real level is unknown; resend the target when it's back."""
        self.expected = None

    def classify(
        self,
        old: Reading,
        new: Reading,
        context_id: str | None,
        now: dt.datetime,
        caps: LightCapabilities,
    ) -> Classification:
        """Spec §7.2: is an on->on report a manual change?"""
        changed: list[str] = []
        if new.brightness is not None and new.brightness != old.brightness:
            changed.append("brightness")
        if caps.color_temp:
            if old.color_mode == "color_temp" and new.color_mode in _COLOR_MODES:
                changed.append("color_mode")
            if (
                new.color_temp_kelvin is not None
                and new.color_temp_kelvin != old.color_temp_kelvin
            ):
                changed.append("color_temp")
        if not changed:
            return Classification(False, "no tracked change")
        if self.is_own_context(context_id):
            return Classification(False, "rule 1: our context")

        reasons: list[str] = []
        for name in changed:
            if name == "color_mode":
                return Classification(True, f"color mode -> {new.color_mode}")
            if name == "brightness":
                assert new.brightness is not None
                reason = self._explain(
                    float(new.brightness),
                    self.expected.brightness if self.expected else None,
                    self.pre_command.brightness if self.pre_command else None,
                    BRIGHTNESS_TOLERANCE,
                    now,
                )
            else:
                assert new.color_temp_kelvin is not None
                expected_k = self.expected.color_temp_kelvin if self.expected else None
                pre_k = self.pre_command.color_temp_kelvin if self.pre_command else None
                reason = self._explain(
                    _mired(new.color_temp_kelvin),
                    None if expected_k is None else _mired(expected_k),
                    None if pre_k is None else _mired(pre_k),
                    MIRED_TOLERANCE,
                    now,
                )
            if reason is None:
                return Classification(True, f"{name} {self._value(name, new)}")
            reasons.append(f"{name} {reason}")
        return Classification(False, "; ".join(reasons))

    def _explain(
        self,
        value: float,
        expected: float | None,
        pre: float | None,
        tolerance: float,
        now: dt.datetime,
    ) -> str | None:
        """Rule 2 or 3 for one value; returns why it's ours, or None."""
        if expected is None:
            return None
        if abs(value - expected) <= tolerance:
            return f"rule 2: within {tolerance} of {expected:g}"
        if pre is None or self.sent_at is None:
            return None
        deadline = self.sent_at + dt.timedelta(seconds=self.fade_s + SETTLE_SECONDS)
        low, high = min(pre, expected) - tolerance, max(pre, expected) + tolerance
        if now <= deadline and low <= value <= high:
            return f"rule 3: between {pre:g} and {expected:g}"
        return None

    @staticmethod
    def _value(name: str, reading: Reading) -> str:
        if name == "brightness":
            return f"{reading.brightness}/255"
        return f"{reading.color_temp_kelvin} K"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: `91 passed`.

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add custom_components/light_manager/light_tracker.py tests/test_light_tracker.py
git commit -m "Add light tracker: manual-override classification"
```

---

### Task 5: Runtime (groups, manager, persistence)

**Files:**
- Create: `custom_components/light_manager/members.py`, `group.py`, `manager.py`
- Modify: `custom_components/light_manager/__init__.py` (full replacement)
- Modify: `tests/conftest.py` (full replacement)
- Create: `tests/common.py`
- Test: `tests/test_members.py`, `tests/test_runtime.py`, `tests/test_holds.py`, `tests/test_restore.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  - `members.expand_lights(hass, entity_ids) -> tuple[list[str], list[str]]`: returns (member lights, Group helpers), order-preserving and deduplicated.
  - `group.Hold(phase, pressed_at, expiry)`.
  - `group.PhaseState(phase: Phase, progress: int | None, held: bool, next_day_target, next_night_target, overridden_lights: list[str])`.
  - `group.GroupRuntime`:
    - Attributes: `hass`, `subentry_id`, `config: GroupConfig`, `schedule`, `enabled`, `hold`, `trackers`. Property `active`.
    - Methods:
      - `async_start(stored)`, `async_stop()`
      - `async_add_listener(cb) -> unsub`
      - `async_set_enabled(bool)`, `async_activate()`, `async_press(Phase)`
      - `phase_state() -> PhaseState`, `as_store() -> dict`
  - `manager.Manager(hass, entry)`:
    - Attributes: `entry`, `global_enabled`, `groups: dict[subentry_id, GroupRuntime]`.
    - Methods:
      - `async_start()`, `async_stop()`, `async_schedule_save()`
      - `is_explicit_context(cid) -> bool`
      - `async_set_global_enabled(bool)`, `async_press_all(Phase)`
      - `async_add_listener(cb) -> unsub`
  - `__init__.py`: `type LightManagerConfigEntry = ConfigEntry[Manager]` and `PLATFORMS` (empty until Task 7). The update listener reloads the entry when any entry or subentry changes.
  - Tests:
    - `tests/common.py`: `PACIFIC`, `ENTRY_ID = "lm_entry"`, `STORAGE_KEY`, `local(...)`, `group_data(**changes)`, `advance_to(hass, freezer, when)`, and `FakeLights`.
    - `tests/conftest.py`: fixtures `lights` and `setup_integration(*groups, stored=None)`.

- [ ] **Step 1: Write the test helpers**

Create `tests/common.py`:

```python
"""Test helpers: fake lights, group data and clock control."""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_fire_time_changed

PACIFIC = ZoneInfo("US/Pacific")
ENTRY_ID = "lm_entry"
STORAGE_KEY = f"light_manager.{ENTRY_ID}"
_OFF_ATTRS = ("brightness", "color_temp_kelvin", "color_mode")


def local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> dt.datetime:
    """A US/Pacific datetime (the hass test fixture's time zone)."""
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=PACIFIC)


def group_data(**changes: Any) -> dict[str, Any]:
    """Subentry data for a group with fixed 07:00/21:00 targets and two lights."""
    data: dict[str, Any] = {
        "name": "Living room",
        "lights": ["light.lamp", "light.dimmer"],
        "day": {"brightness_pct": 100, "color_temp_kelvin": 4000},
        "night": {"brightness_pct": 20, "color_temp_kelvin": 2200},
        "day_target": {"type": "fixed", "time": "07:00:00"},
        "night_target": {"type": "fixed", "time": "21:00:00"},
        "transition_min": 30,
        "off_behavior": "return_to_auto",
        "light_overrides": {},
    }
    data.update(changes)
    return data


async def advance_to(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: dt.datetime
) -> None:
    """Move the clock and run every timer that is now due."""
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


class FakeLights:
    """Lights backed by hass.states plus a recording light.turn_on/turn_off.

    turn_on writes the new state with the caller's context, like a real light.
    Entities in `fail` raise; entities in `silent` accept calls without
    reporting (a Z-Wave dimmer that reports later via `update`).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[ServiceCall] = []
        self.fail: set[str] = set()
        self.silent: set[str] = set()
        hass.services.async_register("light", "turn_on", self._async_turn_on)
        hass.services.async_register("light", "turn_off", self._async_turn_off)

    def add_color_temp(
        self,
        entity_id: str,
        state: str = "on",
        brightness: int = 255,
        kelvin: int = 4000,
        min_kelvin: int = 2000,
        max_kelvin: int = 6500,
    ) -> None:
        on = state == "on"
        self.hass.states.async_set(
            entity_id,
            state,
            {
                "supported_color_modes": ["color_temp"],
                "min_color_temp_kelvin": min_kelvin,
                "max_color_temp_kelvin": max_kelvin,
                "color_mode": "color_temp" if on else None,
                "brightness": brightness if on else None,
                "color_temp_kelvin": kelvin if on else None,
            },
        )

    def add_dimmer(
        self, entity_id: str, state: str = "on", brightness: int = 255
    ) -> None:
        on = state == "on"
        self.hass.states.async_set(
            entity_id,
            state,
            {
                "supported_color_modes": ["brightness"],
                "color_mode": "brightness" if on else None,
                "brightness": brightness if on else None,
            },
        )

    def set(
        self,
        entity_id: str,
        state: str,
        context: Context | None = None,
        **attrs: Any,
    ) -> None:
        """Change state with a fresh context (a wall switch or a device report)."""
        current = self.hass.states.get(entity_id)
        merged = dict(current.attributes) if current else {}
        if state != "on":
            merged.update(dict.fromkeys(_OFF_ATTRS))
        elif merged.get("color_mode") is None and merged.get("supported_color_modes"):
            merged["color_mode"] = merged["supported_color_modes"][0]
        merged.update(attrs)
        self.hass.states.async_set(
            entity_id, state, merged, context=context or Context()
        )

    def update(self, entity_id: str, context: Context | None = None, **attrs: Any):
        """An on -> on report with changed attributes."""
        self.set(entity_id, "on", context=context, **attrs)

    def calls_for(self, entity_id: str) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in call.data.items() if k != "entity_id"}
            for call in self.calls
            if call.data["entity_id"] == entity_id
        ]

    def clear(self) -> None:
        self.calls.clear()

    async def _async_turn_on(self, call: ServiceCall) -> None:
        self.calls.append(call)
        entity_id = call.data["entity_id"]
        if entity_id in self.fail:
            raise HomeAssistantError(f"{entity_id} did not respond")
        if entity_id in self.silent:
            return
        state = self.hass.states.get(entity_id)
        attrs = dict(state.attributes) if state else {}
        modes = attrs.get("supported_color_modes") or []
        attrs["color_mode"] = attrs.get("color_mode") or (modes[0] if modes else None)
        if "brightness" in call.data:
            attrs["brightness"] = call.data["brightness"]
        if "brightness_pct" in call.data:
            attrs["brightness"] = round(call.data["brightness_pct"] * 255 / 100)
        if "color_temp_kelvin" in call.data and "color_temp" in modes:
            attrs["color_temp_kelvin"] = call.data["color_temp_kelvin"]
            attrs["color_mode"] = "color_temp"
        self.hass.states.async_set(entity_id, "on", attrs, context=call.context)

    async def _async_turn_off(self, call: ServiceCall) -> None:
        self.calls.append(call)
        self.set(call.data["entity_id"], "off", context=call.context)
```

Replace `tests/conftest.py` with:

```python
"""Shared fixtures."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.light_manager.const import DOMAIN

from .common import ENTRY_ID, STORAGE_KEY, FakeLights

type SetupIntegration = Callable[..., Awaitable[MockConfigEntry]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load custom_components/ in every test that uses hass."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")


@pytest.fixture
def lights(hass: HomeAssistant) -> FakeLights:
    return FakeLights(hass)


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> AsyncGenerator[SetupIntegration]:
    """Factory: set up the parent entry with group subentries (and stored state).

    Groups get subentry IDs group_1, group_2, ... in order. The entry is
    unloaded at teardown so timers and listeners are cleaned up.
    """
    entries: list[MockConfigEntry] = []

    async def _setup(
        *groups: dict[str, Any], stored: dict[str, Any] | None = None
    ) -> MockConfigEntry:
        if stored is not None:
            hass_storage[STORAGE_KEY] = {
                "version": 1,
                "minor_version": 1,
                "key": STORAGE_KEY,
                "data": stored,
            }
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id=ENTRY_ID,
            title="Light Manager",
            data={},
            subentries_data=[
                {
                    "data": data,
                    "subentry_id": f"group_{index}",
                    "subentry_type": "group",
                    "title": data["name"],
                    "unique_id": None,
                }
                for index, data in enumerate(groups, start=1)
            ],
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entries.append(entry)
        return entry

    yield _setup
    for entry in entries:
        if entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_members.py`:

```python
"""Tests for members.py (Group-helper expansion, spec §10)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.light_manager.members import expand_lights


def add_helper(hass: HomeAssistant, object_id: str, members: list[str] | None) -> str:
    entry = er.async_get(hass).async_get_or_create(
        "light", "group", object_id, suggested_object_id=object_id
    )
    if members is not None:
        hass.states.async_set(entry.entity_id, "on", {"entity_id": members})
    return entry.entity_id


async def test_plain_lights_pass_through_in_order_without_duplicates(
    hass: HomeAssistant,
) -> None:
    lights, helpers = expand_lights(hass, ["light.b", "light.a", "light.b"])

    assert lights == ["light.b", "light.a"]
    assert helpers == []


async def test_helpers_expand_recursively(hass: HomeAssistant) -> None:
    upstairs = add_helper(hass, "upstairs", ["light.bed", "light.hall"])
    house = add_helper(hass, "house", [upstairs, "light.kitchen", "light.hall"])

    lights, helpers = expand_lights(hass, [house, "light.porch"])

    assert lights == ["light.bed", "light.hall", "light.kitchen", "light.porch"]
    assert helpers == [house, upstairs]


async def test_helper_without_state_has_no_members_yet(hass: HomeAssistant) -> None:
    helper = add_helper(hass, "later", None)

    assert expand_lights(hass, [helper]) == ([], [helper])


async def test_non_group_light_with_entity_id_attribute_is_a_light(
    hass: HomeAssistant,
) -> None:
    # A Hue room or Zigbee2MQTT group: not an HA Group helper, so one light.
    hass.states.async_set("light.hue_room", "on", {"entity_id": ["light.x"]})

    assert expand_lights(hass, ["light.hue_room"]) == (["light.hue_room"], [])


async def test_helper_cycles_terminate(hass: HomeAssistant) -> None:
    first = er.async_get(hass).async_get_or_create(
        "light", "group", "first", suggested_object_id="first"
    )
    second = add_helper(hass, "second", [first.entity_id, "light.lamp"])
    hass.states.async_set(first.entity_id, "on", {"entity_id": [second]})

    lights, helpers = expand_lights(hass, [first.entity_id])

    assert lights == ["light.lamp"]
    assert helpers == [first.entity_id, second]
```

Create `tests/test_runtime.py`:

```python
"""Runtime tests: ramps, overrides, turn-on handling and failures (fake clock)."""

import datetime as dt
import logging

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.light_manager.light_tracker import Mode
from custom_components.light_manager.models import Phase

from .common import FakeLights, advance_to, group_data, local
from .conftest import SetupIntegration

NOON = local(2026, 9, 30, 12, 0)
DAY_CMD = {"brightness": 255, "color_temp_kelvin": 4000, "transition": 2}


def runtime(entry, subentry_id: str = "group_1"):
    return entry.runtime_data.groups[subentry_id]


async def start(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    lights: FakeLights,
    setup_integration: SetupIntegration,
    when: dt.datetime = NOON,
    **changes,
):
    """Lamp (color temp) and dimmer on at full; integration set up at `when`."""
    freezer.move_to(when)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    entry = await setup_integration(group_data(**changes))
    return entry


async def test_startup_sends_current_target_to_lights_that_are_on(
    hass, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp", brightness=100, kelvin=3000)
    lights.add_dimmer("light.dimmer", state="off")

    await setup_integration(group_data())

    assert lights.calls_for("light.lamp") == [DAY_CMD]
    assert lights.calls_for("light.dimmer") == []


async def test_full_ramp_commands_every_tick_and_lands_on_target(
    hass, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration, local(2026, 9, 30, 20, 0))
    lights.clear()

    moment = local(2026, 9, 30, 20, 30)
    while moment <= local(2026, 9, 30, 21, 0):
        await advance_to(hass, freezer, moment)
        moment += dt.timedelta(seconds=30)

    lamp = lights.calls_for("light.lamp")
    dimmer = lights.calls_for("light.dimmer")
    assert len(lamp) == 61
    assert len(dimmer) == 61
    assert lamp[0] == DAY_CMD
    assert lamp[20] == {"brightness": 187, "color_temp_kelvin": 3143, "transition": 2}
    assert lamp[40] == {"brightness": 119, "color_temp_kelvin": 2588, "transition": 2}
    assert lamp[-1] == {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    assert dimmer[-1] == {"brightness": 51, "transition": 2}

    lights.clear()
    await advance_to(hass, freezer, local(2026, 9, 30, 23, 0))
    assert lights.calls == []


async def test_manual_change_overrides_only_that_light(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(
        hass, freezer, lights, setup_integration, local(2026, 9, 30, 20, 40)
    )

    # The user dims the lamp after our command's settle window has passed.
    freezer.tick(dt.timedelta(seconds=15))
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()
    lights.clear()
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 41))

    assert lights.calls_for("light.lamp") == []
    assert len(lights.calls_for("light.dimmer")) == 1
    assert runtime(entry).phase_state().overridden_lights == ["light.lamp"]


async def test_late_and_mid_fade_reports_are_not_overrides(
    hass, freezer, lights, setup_integration
) -> None:
    # A Z-Wave dimmer at full that only reports on its own schedule.
    freezer.move_to(local(2026, 9, 30, 22, 0))
    lights.add_dimmer("light.dimmer", brightness=255)
    lights.silent.add("light.dimmer")
    entry = await setup_integration(group_data(lights=["light.dimmer"]))
    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]

    lights.update("light.dimmer", brightness=150)  # mid-fade, fresh context
    freezer.tick(dt.timedelta(seconds=25))
    lights.update("light.dimmer", brightness=51)  # late final report
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_ramp_start_clears_overrides(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=80)
    await hass.async_block_till_done()
    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    lights.clear()

    await advance_to(hass, freezer, local(2026, 9, 30, 20, 30))

    assert runtime(entry).trackers["light.lamp"].mode is Mode.AUTO
    assert lights.calls_for("light.lamp") == [DAY_CMD]


async def test_overridden_light_off_and_on_returns_to_auto(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=80)
    lights.set("light.lamp", "off")
    lights.set("light.lamp", "on", brightness=80, color_temp_kelvin=3000)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.AUTO
    assert lights.calls_for("light.lamp")[-1] == {
        "brightness": 255,
        "color_temp_kelvin": 4000,
        "transition": 0,
    }


async def test_stay_overridden_survives_off_and_on(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(
        hass, freezer, lights, setup_integration, off_behavior="stay_overridden"
    )
    lights.update("light.lamp", brightness=80)
    lights.set("light.lamp", "off")
    lights.clear()
    lights.set("light.lamp", "on", brightness=80)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []


async def test_plain_turn_on_gets_target_with_no_fade(
    hass, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration, local(2026, 9, 30, 22, 0))
    lights.set("light.dimmer", "off")
    lights.clear()

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.dimmer"}, blocking=True
    )
    await hass.async_block_till_done()

    assert lights.calls_for("light.dimmer") == [{}, {"brightness": 51, "transition": 0}]


async def test_explicit_turn_on_marks_light_overridden(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.set("light.lamp", "off")
    lights.clear()

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.lamp", "brightness_pct": 40},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == [{"brightness_pct": 40}]


async def test_unavailable_round_trip_keeps_mode(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=80)  # override the lamp
    lights.clear()

    for entity_id in ("light.lamp", "light.dimmer"):
        lights.set(entity_id, "unavailable")
        lights.set(entity_id, "on", brightness=100)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []
    assert lights.calls_for("light.dimmer") == [{"brightness": 255, "transition": 0}]


async def test_light_missing_at_startup_gets_target_when_it_appears(
    hass, freezer, lights, setup_integration, caplog
) -> None:
    freezer.move_to(local(2026, 9, 30, 22, 0))
    lights.add_color_temp("light.lamp")
    with caplog.at_level(logging.WARNING):
        entry = await setup_integration(group_data())
    assert "light.dimmer doesn't exist" in caplog.text

    lights.add_dimmer("light.dimmer", brightness=255)  # Z-Wave finished loading
    await hass.async_block_till_done()

    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 0}]
    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_failed_command_does_not_block_others_and_is_retried(
    hass, freezer, lights, setup_integration, caplog
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.fail.add("light.lamp")
    lights.clear()

    with caplog.at_level(logging.WARNING):
        await runtime(entry).async_press(Phase.NIGHT)
    assert "light.lamp: command failed" in caplog.text
    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]
    assert runtime(entry).trackers["light.lamp"].expected is None

    # The next evaluation (20:30, inside the hold so nothing is reset) retries.
    lights.fail.clear()
    lights.clear()
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 30))
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == []


async def test_light_override_values_are_used(
    hass, freezer, lights, setup_integration
) -> None:
    await start(
        hass,
        freezer,
        lights,
        setup_integration,
        local(2026, 9, 30, 22, 0),
        light_overrides={"light.dimmer": {"night_brightness_pct": 5}},
    )

    assert lights.calls_for("light.dimmer") == [{"brightness": 13, "transition": 2}]
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]


async def test_brightness_none_report_while_on_is_not_an_override(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    lights.update("light.dimmer", brightness=None)
    lights.update("light.dimmer", brightness=255)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_group_helper_is_expanded_into_members(
    hass, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "light", "group", "living", suggested_object_id="living_group"
    )
    lights.add_color_temp("light.lamp", brightness=100)
    lights.add_dimmer("light.dimmer", brightness=100)
    lights.add_dimmer("light.extra", brightness=100)
    hass.states.async_set(
        "light.living_group", "on", {"entity_id": ["light.lamp", "light.dimmer"]}
    )

    entry = await setup_integration(group_data(lights=["light.living_group"]))
    assert list(runtime(entry).trackers) == ["light.lamp", "light.dimmer"]
    assert lights.calls_for("light.living_group") == []
    lights.clear()

    hass.states.async_set(
        "light.living_group",
        "on",
        {"entity_id": ["light.lamp", "light.dimmer", "light.extra"]},
    )
    await hass.async_block_till_done()

    assert "light.extra" in runtime(entry).trackers
    assert lights.calls_for("light.extra") == [{"brightness": 255, "transition": 2}]
    assert lights.calls_for("light.lamp") == []


async def test_inactive_group_makes_no_automatic_changes(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    group = runtime(entry)
    await group.async_set_enabled(False)
    lights.clear()

    lights.update("light.lamp", brightness=80)  # not classified while inactive
    lights.set("light.dimmer", "off")
    lights.set("light.dimmer", "on", brightness=10)  # no turn-on handling
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))  # no ramp

    assert lights.calls == []
    assert group.trackers["light.lamp"].mode is Mode.AUTO

    await group.async_set_enabled(True)

    assert lights.calls_for("light.lamp") == [
        {"brightness": 153, "color_temp_kelvin": 2839, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == [{"brightness": 153, "transition": 2}]


@pytest.mark.parametrize("enabled", [True, False])
async def test_group_switch_state_is_saved(
    hass, freezer, lights, setup_integration, hass_storage, enabled
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    await runtime(entry).async_set_enabled(enabled)
    await hass.config_entries.async_unload(entry.entry_id)

    stored = hass_storage["light_manager.lm_entry"]["data"]
    assert stored["groups"]["group_1"]["enabled"] is enabled
```

Create `tests/test_holds.py`:

```python
"""Day now / Night now holds and the global controls (spec §6.5, §8)."""

from homeassistant.core import HomeAssistant

from custom_components.light_manager.light_tracker import Mode
from custom_components.light_manager.models import Phase

from .common import FakeLights, advance_to, group_data, local
from .conftest import SetupIntegration

NOON = local(2026, 9, 30, 12, 0)
NIGHT_LAMP = {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
DAY_LAMP = {"brightness": 255, "color_temp_kelvin": 4000, "transition": 2}


async def start(
    freezer, lights: FakeLights, setup_integration: SetupIntegration, when=NOON
):
    freezer.move_to(when)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    entry = await setup_integration(group_data())
    lights.clear()
    return entry, entry.runtime_data.groups["group_1"]


async def test_night_now_holds_until_the_morning_ramp(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(freezer, lights, setup_integration)

    await group.async_press(Phase.NIGHT)

    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    state = group.phase_state()
    assert state.phase is Phase.NIGHT
    assert state.held is True
    assert group.hold.expiry == local(2026, 10, 1, 6, 30)

    # An override made during the hold survives the suppressed evening ramp.
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()
    lights.clear()
    for moment in (local(2026, 9, 30, 20, 30), local(2026, 9, 30, 20, 45)):
        await advance_to(hass, freezer, moment)
    assert lights.calls == []
    assert group.trackers["light.lamp"].mode is Mode.OVERRIDDEN

    # The hold ends when the to_day ramp starts; that ramp clears overrides.
    await advance_to(hass, freezer, local(2026, 10, 1, 6, 30))
    assert group.hold is None
    assert group.trackers["light.lamp"].mode is Mode.AUTO
    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    assert group.phase_state().phase is Phase.TO_DAY


async def test_day_now_mid_ramp_cancels_the_ramp(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(
        freezer, lights, setup_integration, local(2026, 9, 30, 20, 40)
    )

    await group.async_press(Phase.DAY)
    assert lights.calls_for("light.lamp") == [DAY_LAMP]
    lights.clear()

    for moment in (local(2026, 9, 30, 20, 40, 30), local(2026, 9, 30, 21, 0)):
        await advance_to(hass, freezer, moment)

    assert lights.calls == []
    assert group.phase_state().phase is Phase.DAY
    assert group.hold.expiry == local(2026, 10, 1, 20, 30)


async def test_press_resends_a_target_equal_to_the_last_command(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=30)  # user override
    await hass.async_block_till_done()

    # The last command sent to the lamp was the day setpoint; it must be resent.
    await group.async_press(Phase.DAY)

    assert lights.calls_for("light.lamp") == [DAY_LAMP]
    assert group.trackers["light.lamp"].mode is Mode.AUTO


async def test_group_button_works_while_the_group_is_disabled(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(freezer, lights, setup_integration)
    await group.async_set_enabled(False)

    await group.async_press(Phase.NIGHT)
    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    lights.clear()

    lights.set("light.lamp", "off")
    lights.set("light.lamp", "on", brightness=200)  # no turn-on handling
    await advance_to(hass, freezer, local(2026, 10, 1, 6, 45))  # no ramp
    assert lights.calls == []


async def test_global_press_skips_groups_whose_switch_is_off(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    lights.add_dimmer("light.porch")
    entry = await setup_integration(
        group_data(),
        group_data(name="Porch", lights=["light.porch"]),
    )
    manager = entry.runtime_data
    await manager.groups["group_2"].async_set_enabled(False)
    await manager.async_set_global_enabled(False)  # global switch doesn't matter
    lights.clear()

    await manager.async_press_all(Phase.NIGHT)

    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    assert lights.calls_for("light.porch") == []


async def test_global_switch_stops_and_reactivates_groups(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry, group = await start(freezer, lights, setup_integration)
    manager = entry.runtime_data

    await manager.async_set_global_enabled(False)
    assert group.active is False
    lights.update("light.lamp", brightness=30)
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))
    assert lights.calls == []

    await manager.async_set_global_enabled(True)

    assert group.active is True
    assert lights.calls_for("light.lamp") == [
        {"brightness": 153, "color_temp_kelvin": 2839, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == [{"brightness": 153, "transition": 2}]


async def test_group_switch_on_with_global_off_stays_inactive(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry, group = await start(freezer, lights, setup_integration)
    await entry.runtime_data.async_set_global_enabled(False)
    await group.async_set_enabled(False)

    await group.async_set_enabled(True)

    assert group.active is False
    assert lights.calls == []
```

Create `tests/test_restore.py`:

```python
"""Restore after restart/reload (spec §9)."""

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.light_manager.light_tracker import Mode
from custom_components.light_manager.models import Phase

from .common import STORAGE_KEY, group_data, local

NOON = local(2026, 9, 30, 12, 0)


def stored(**group: Any) -> dict[str, Any]:
    return {
        "global_enabled": True,
        "groups": {
            "group_1": {"enabled": True, "hold": None, "overridden": {}, **group}
        },
    }


def iso(*args: int) -> str:
    return local(*args).isoformat()


async def test_active_hold_is_restored(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 13, 0))
    lights.add_color_temp("light.lamp")
    hold = {"phase": "night", "pressed_at": iso(2026, 9, 30, 12, 0)}

    entry = await setup_integration(group_data(), stored=stored(hold=hold))

    group = entry.runtime_data.groups["group_1"]
    assert group.phase_state().held is True
    assert group.phase_state().phase is Phase.NIGHT
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]


async def test_expired_hold_is_dropped(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    hold = {"phase": "night", "pressed_at": iso(2026, 9, 29, 12, 0)}

    entry = await setup_integration(group_data(), stored=stored(hold=hold))

    group = entry.runtime_data.groups["group_1"]
    assert group.hold is None
    assert group.phase_state().phase is Phase.DAY


async def test_override_kept_when_no_ramp_started_since(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 14, 0))
    lights.add_color_temp("light.lamp", brightness=30)
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN
    assert tracker.overridden_at == local(2026, 9, 30, 13, 0)
    assert lights.calls_for("light.lamp") == []


async def test_override_dropped_after_a_ramp_started(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp", brightness=30)
    data = stored(overridden={"light.lamp": iso(2026, 9, 29, 19, 0)})

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.AUTO
    assert len(lights.calls_for("light.lamp")) == 1


async def test_override_survives_a_ramp_suppressed_by_the_hold(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 21, 30))
    lights.add_color_temp("light.lamp", brightness=30)
    data = stored(
        hold={"phase": "night", "pressed_at": iso(2026, 9, 30, 12, 0)},
        overridden={"light.lamp": iso(2026, 9, 30, 15, 0)},
    )

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN


async def test_return_to_auto_override_dropped_for_light_known_off(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 14, 0))
    lights.add_color_temp("light.lamp", state="off")
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.AUTO


async def test_override_kept_for_off_light_with_stay_overridden(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 14, 0))
    lights.add_color_temp("light.lamp", state="off")
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(
        group_data(off_behavior="stay_overridden"), stored=data
    )

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN


async def test_override_kept_while_light_has_not_loaded_yet(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    # Z-Wave can finish loading after us: unknown state is not "known off".
    freezer.move_to(local(2026, 9, 30, 14, 0))
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(), stored=data)
    lights.add_color_temp("light.lamp", brightness=30)
    await hass.async_block_till_done()

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []


async def test_switch_states_are_restored(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    data = stored(enabled=False)
    data["global_enabled"] = False

    entry = await setup_integration(group_data(), stored=data)

    assert entry.runtime_data.global_enabled is False
    assert entry.runtime_data.groups["group_1"].enabled is False
    assert lights.calls == []


async def test_state_saved_on_unload_and_unknown_groups_dropped(
    hass: HomeAssistant, freezer, lights, setup_integration, hass_storage
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    data = stored()
    data["groups"]["deleted_group"] = {"enabled": False, "hold": None, "overridden": {}}
    entry = await setup_integration(group_data(), stored=data)
    group = entry.runtime_data.groups["group_1"]
    await group.async_press(Phase.NIGHT)
    freezer.tick(60)
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(entry.entry_id)

    saved = hass_storage[STORAGE_KEY]["data"]
    assert set(saved["groups"]) == {"group_1"}
    assert saved["groups"]["group_1"] == {
        "enabled": True,
        "hold": {"phase": "night", "pressed_at": "2026-09-30T19:00:00+00:00"},
        "overridden": {"light.lamp": "2026-09-30T19:01:00+00:00"},
    }
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_members.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'custom_components.light_manager.members'`. (The runtime tests can't set anything up yet either; Task 1's `__init__.py` has no `async_setup_entry`.)

- [ ] **Step 4: Implement the runtime**

Create `custom_components/light_manager/members.py`:

```python
"""Group membership: expand HA Group-helper lights into their members (spec §10)."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def expand_lights(
    hass: HomeAssistant, entity_ids: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Return (member lights, group helpers), order-preserving, without duplicates.

    A light whose registry entry has platform "group" is a helper: its state's
    entity_id attribute lists its members, expanded recursively. A helper with no
    state yet has no members. Anything else (including lights not loaded yet) is
    a member light.
    """
    registry = er.async_get(hass)
    lights: list[str] = []
    helpers: list[str] = []

    def visit(entity_id: str, path: frozenset[str]) -> None:
        if entity_id in path:
            return
        entry = registry.async_get(entity_id)
        if entry is not None and entry.platform == "group":
            if entity_id not in helpers:
                helpers.append(entity_id)
            state = hass.states.get(entity_id)
            members = state.attributes.get(ATTR_ENTITY_ID, []) if state else []
            for member in members:
                visit(member, path | {entity_id})
        elif entity_id not in lights:
            lights.append(entity_id)

    for entity_id in entity_ids:
        visit(entity_id, frozenset())
    return lights, helpers
```

Create `custom_components/light_manager/group.py`:

```python
"""GroupRuntime: drives one light group (timers, state listeners, commands, holds)."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ATTR_TRANSITION
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import (
    Context,
    Event,
    EventStateChangedData,
    HassJob,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    OFF_RETURN_TO_AUTO,
    OFF_STAY_OVERRIDDEN,
    STEP_FADE_SECONDS,
    TICK_SECONDS,
)
from .curve import (
    LightCommand,
    capabilities_from_attributes,
    effective_setpoints,
    light_command,
    setpoint_at,
)
from .light_tracker import LightTracker, Mode, Reading
from .members import expand_lights
from .models import RAMP_PHASES, GroupConfig, Phase
from .schedule import Schedule

if TYPE_CHECKING:
    from .manager import Manager

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Hold:
    """Day now / Night now: pin a phase until the next opposite ramp starts."""

    phase: Phase
    pressed_at: dt.datetime
    expiry: dt.datetime | None

    def active(self, now: dt.datetime) -> bool:
        return self.expiry is None or now < self.expiry

    def covers(self, moment: dt.datetime) -> bool:
        """True if a ramp starting at `moment` is suppressed by this hold."""
        return self.pressed_at <= moment and (
            self.expiry is None or moment < self.expiry
        )


@dataclass(frozen=True, slots=True)
class PhaseState:
    """What the phase sensor shows."""

    phase: Phase
    progress: int | None  # 0-100 during a ramp
    held: bool
    next_day_target: dt.datetime | None
    next_night_target: dt.datetime | None
    overridden_lights: list[str]


class GroupRuntime:
    """One light group: the schedule, its member lights and their trackers."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: Manager,
        subentry_id: str,
        config: GroupConfig,
        schedule: Schedule,
    ) -> None:
        self.hass = hass
        self._manager = manager
        self.subentry_id = subentry_id
        self.config = config
        self.schedule = schedule
        self.enabled = True
        self.hold: Hold | None = None
        self.trackers: dict[str, LightTracker] = {}
        self._helpers: set[str] = set()
        self._last_eval = dt_util.utcnow()
        self._listeners: list[Callable[[], None]] = []
        self._unsub_state: Callable[[], None] | None = None
        self._unsub_timer: Callable[[], None] | None = None
        self._logged_on_off: set[str] = set()

    @property
    def active(self) -> bool:
        """Spec §8: both the global switch and the group's switch are on."""
        return self._manager.global_enabled and self.enabled

    # --- lifecycle ---

    async def async_start(self, stored: dict[str, Any] | None) -> None:
        lights, helpers = expand_lights(self.hass, self.config.lights)
        self._set_members(lights, helpers)
        registry = er.async_get(self.hass)
        for entity_id in lights:
            if registry.async_get(entity_id) is None and not self.hass.states.get(
                entity_id
            ):
                _LOGGER.warning(
                    "%s: %s doesn't exist; it's skipped until it appears",
                    self.config.name,
                    entity_id,
                )
        now = dt_util.utcnow()
        self._restore(stored, now)
        self._last_eval = now
        self._schedule_next(now)
        if self.active:
            self._create_task(self._async_apply(STEP_FADE_SECONDS))

    @callback
    def async_stop(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Entities subscribe here to be told when to re-render."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # --- controls ---

    async def async_set_enabled(self, enabled: bool) -> None:
        was_active = self.active
        self.enabled = enabled
        if self.active and not was_active:
            await self.async_activate()
        self._manager.async_schedule_save()
        self._notify()

    async def async_activate(self) -> None:
        """Spec §8: on becoming active, clear overrides and apply the target."""
        self._reset_all()
        await self._async_apply(STEP_FADE_SECONDS)
        self._notify()

    async def async_press(self, phase: Phase) -> None:
        """Spec §6.5: Day now / Night now. Works even while inactive."""
        now = dt_util.utcnow()
        self.hold = Hold(phase, now, self.schedule.hold_expiry(phase, now))
        self._reset_all()
        self._schedule_next(now)
        await self._async_apply(STEP_FADE_SECONDS)
        self._manager.async_schedule_save()
        self._notify()

    # --- state for entities and storage ---

    def phase_state(self) -> PhaseState:
        now = dt_util.utcnow()
        info = self.schedule.phase_at(now)
        held = self.hold is not None and self.hold.active(now)
        if held:
            assert self.hold is not None
            phase, progress = self.hold.phase, None
        else:
            phase = info.phase
            progress = None if info.progress is None else round(info.progress * 100)
        return PhaseState(
            phase=phase,
            progress=progress,
            held=held,
            next_day_target=info.next_day_target,
            next_night_target=info.next_night_target,
            overridden_lights=sorted(
                entity_id
                for entity_id, tracker in self.trackers.items()
                if tracker.mode is Mode.OVERRIDDEN
            ),
        )

    def as_store(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hold": None
            if self.hold is None
            else {
                "phase": self.hold.phase.value,
                "pressed_at": self.hold.pressed_at.isoformat(),
            },
            "overridden": {
                entity_id: tracker.overridden_at.isoformat()
                for entity_id, tracker in self.trackers.items()
                if tracker.mode is Mode.OVERRIDDEN and tracker.overridden_at
            },
        }

    def _restore(self, stored: dict[str, Any] | None, now: dt.datetime) -> None:
        """Spec §9: restore what is still valid after a restart or reload."""
        if not stored:
            return
        self.enabled = stored.get("enabled", True)
        hold: Hold | None = None
        if (data := stored.get("hold")) and (
            pressed_at := dt_util.parse_datetime(data["pressed_at"])
        ):
            phase = Phase(data["phase"])
            hold = Hold(phase, pressed_at, self.schedule.hold_expiry(phase, pressed_at))
        self.hold = hold if hold is not None and hold.active(now) else None
        for entity_id, iso in stored.get("overridden", {}).items():
            tracker = self.trackers.get(entity_id)
            since = dt_util.parse_datetime(iso)
            if tracker is None or since is None:
                continue
            if self._cleared_by_ramp(since, now, hold):
                continue
            state = self.hass.states.get(entity_id)
            if (
                self.config.off_behavior == OFF_RETURN_TO_AUTO
                and state is not None
                and state.state == STATE_OFF
            ):
                continue
            tracker.mark_overridden(since)

    def _cleared_by_ramp(
        self, since: dt.datetime, now: dt.datetime, hold: Hold | None
    ) -> bool:
        """Spec §7.3: did a ramp start in (since, now] that no hold suppressed?"""
        return any(
            hold is None or not hold.covers(start)
            for start in self.schedule.ramp_starts_between(since, now)
        )

    # --- evaluation ---

    async def _async_on_timer(self, _scheduled: dt.datetime) -> None:
        await self._async_evaluate(dt_util.utcnow())

    async def _async_evaluate(self, now: dt.datetime) -> None:
        try:
            cleared = self._cleared_by_ramp(self._last_eval, now, self.hold)
            self._last_eval = now
            if self.hold is not None and not self.hold.active(now):
                self.hold = None
                self._manager.async_schedule_save()
            self._schedule_next(now)
            if self.active:
                if cleared:
                    self._reset_all()
                await self._async_apply(STEP_FADE_SECONDS)
        finally:
            self._notify()

    def _schedule_next(self, now: dt.datetime) -> None:
        """One timer: the next tick during a ramp, else the next ramp start."""
        info = self.schedule.phase_at(now)
        if info.phase in RAMP_PHASES and info.target is not None:
            wake = min(now + dt.timedelta(seconds=TICK_SECONDS), info.target)
        else:
            wake = info.window_start or info.target or now + dt.timedelta(days=1)
        if self.hold is not None and self.hold.expiry is not None:
            wake = min(wake, self.hold.expiry)
        if self._unsub_timer:
            self._unsub_timer()
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass,
            HassJob(self._async_on_timer, cancel_on_shutdown=True),
            wake,
        )

    def _effective_phase(self, now: dt.datetime) -> tuple[Phase, float | None]:
        """Spec §6.5: the held phase while a hold is active, else the schedule's."""
        if self.hold is not None and self.hold.active(now):
            return self.hold.phase, None
        info = self.schedule.phase_at(now)
        return info.phase, info.progress

    async def _async_apply(
        self, fade: float, only: Iterable[str] | None = None
    ) -> None:
        """Send the current target to AUTO lights that are on and need it."""
        now = dt_util.utcnow()
        phase, progress = self._effective_phase(now)
        targets = set(only) if only is not None else None
        sends: list[Coroutine[Any, Any, None]] = []
        for entity_id, tracker in self.trackers.items():
            if targets is not None and entity_id not in targets:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state != STATE_ON:
                continue
            day, night = effective_setpoints(
                self.config.day,
                self.config.night,
                self.config.light_overrides.get(entity_id),
            )
            pct, kelvin = setpoint_at(day, night, phase, progress)
            command = light_command(
                pct, kelvin, capabilities_from_attributes(state.attributes)
            )
            if command is None:
                if entity_id not in self._logged_on_off:
                    self._logged_on_off.add(entity_id)
                    _LOGGER.debug("%s: on/off only; never commanded", entity_id)
                continue
            if tracker.should_send(command):
                reading = Reading.from_attributes(state.attributes)
                sends.append(self._async_send(tracker, command, fade, reading, now))
        if sends:
            await asyncio.gather(*sends)

    async def _async_send(
        self,
        tracker: LightTracker,
        command: LightCommand,
        fade: float,
        current: Reading,
        now: dt.datetime,
    ) -> None:
        context = Context()
        previous = tracker.begin_command(command, context.id, now, fade, current)
        _LOGGER.debug("%s: send %s (fade %ss)", tracker.entity_id, command, fade)
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_ON,
                {
                    ATTR_ENTITY_ID: tracker.entity_id,
                    **command.service_data(),
                    ATTR_TRANSITION: fade,
                },
                blocking=True,
                context=context,
            )
        except Exception as err:  # any failure: roll back so it is retried
            tracker.command_failed(previous)
            _LOGGER.warning("%s: command failed: %s", tracker.entity_id, err)

    # --- membership and light state ---

    def _set_members(self, lights: list[str], helpers: list[str]) -> None:
        self.trackers = {
            entity_id: self.trackers.get(entity_id) or LightTracker(entity_id)
            for entity_id in lights
        }
        self._helpers = set(helpers)
        if self._unsub_state:
            self._unsub_state()
        self._unsub_state = async_track_state_change_event(
            self.hass, [*lights, *helpers], self._async_on_state
        )

    @callback
    def _refresh_members(self) -> None:
        lights, helpers = expand_lights(self.hass, self.config.lights)
        if lights == list(self.trackers) and set(helpers) == self._helpers:
            return
        added = [entity_id for entity_id in lights if entity_id not in self.trackers]
        self._set_members(lights, helpers)
        if added and self.active:
            self._create_task(self._async_apply(STEP_FADE_SECONDS, only=added))
        self._manager.async_schedule_save()
        self._notify()

    @callback
    def _async_on_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if entity_id in self._helpers:
            self._refresh_members()
            return
        tracker = self.trackers.get(entity_id)
        if tracker is None or not self.active:
            return
        old, new = event.data["old_state"], event.data["new_state"]
        old_state = old.state if old else None
        if new is None or new.state != STATE_ON:
            if new is not None and new.state == STATE_OFF:
                if tracker.on_turned_off(self.config.off_behavior):
                    self._changed()
            else:
                tracker.on_unavailable()
            return
        if old_state == STATE_OFF:
            self._handle_turn_on(tracker, new.context.id)
        elif old_state == STATE_ON:
            assert old is not None
            self._handle_report(tracker, old, new)
        elif tracker.mode is Mode.AUTO:
            # unavailable/unknown/new -> on: not a turn-on; catch it up silently.
            self._create_task(self._async_apply(0, only=[entity_id]))

    def _handle_turn_on(self, tracker: LightTracker, context_id: str) -> None:
        """Spec §7.4."""
        if self._manager.is_explicit_context(context_id) and not tracker.is_own_context(
            context_id
        ):
            _LOGGER.debug("%s: explicit turn-on -> overridden", tracker.entity_id)
            tracker.mark_overridden(dt_util.utcnow())
            self._changed()
            return
        if tracker.mode is Mode.OVERRIDDEN:
            if self.config.off_behavior == OFF_STAY_OVERRIDDEN:
                return
            tracker.reset_auto()
            self._changed()
        self._create_task(self._async_apply(0, only=[tracker.entity_id]))

    def _handle_report(self, tracker: LightTracker, old: State, new: State) -> None:
        """Spec §7.2: classify an on->on report from an AUTO light."""
        if tracker.mode is not Mode.AUTO:
            return
        result = tracker.classify(
            Reading.from_attributes(old.attributes),
            Reading.from_attributes(new.attributes),
            new.context.id,
            dt_util.utcnow(),
            capabilities_from_attributes(new.attributes),
        )
        _LOGGER.debug(
            "%s: report -> %s (%s)",
            tracker.entity_id,
            "manual" if result.manual else "ours",
            result.reason,
        )
        if result.manual:
            tracker.mark_overridden(dt_util.utcnow())
            self._changed()

    # --- helpers ---

    def _reset_all(self) -> None:
        for tracker in self.trackers.values():
            tracker.reset_auto()
        self._manager.async_schedule_save()

    def _changed(self) -> None:
        self._manager.async_schedule_save()
        self._notify()

    def _create_task(self, coro: Coroutine[Any, Any, None]) -> None:
        self._manager.entry.async_create_task(self.hass, coro)
```

Create `custom_components/light_manager/manager.py`:

```python
"""Manager: owns the group runtimes, global controls and persistence."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import Any

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    EVENT_CALL_SERVICE,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EXPLICIT_CONTEXT_SECONDS,
    SAVE_DELAY_SECONDS,
    STORAGE_VERSION,
    SUBENTRY_TYPE_GROUP,
)
from .group import GroupRuntime
from .light_tracker import is_explicit_turn_on
from .models import GroupConfig, Phase
from .schedule import Schedule


class Manager:
    """Everything one Light Manager config entry runs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.global_enabled = True
        self.groups: dict[str, GroupRuntime] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._explicit: dict[str, dt.datetime] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsub_call_service: Callable[[], None] | None = None

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.global_enabled = stored.get("global_enabled", True)
        tz = dt_util.get_default_time_zone()
        for subentry_id, subentry in self.entry.subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_GROUP:
                continue
            config = GroupConfig.from_data(subentry.data)
            schedule = Schedule(
                config.day_target,
                config.night_target,
                config.transition,
                self._sun,
                tz,
            )
            self.groups[subentry_id] = GroupRuntime(
                self.hass, self, subentry_id, config, schedule
            )
        self._unsub_call_service = self.hass.bus.async_listen(
            EVENT_CALL_SERVICE, self._async_on_call_service
        )
        stored_groups = stored.get("groups", {})
        for subentry_id, runtime in self.groups.items():
            await runtime.async_start(stored_groups.get(subentry_id))
        self.async_schedule_save()  # drops groups that no longer exist

    async def async_stop(self) -> None:
        if self._unsub_call_service:
            self._unsub_call_service()
            self._unsub_call_service = None
        for runtime in self.groups.values():
            runtime.async_stop()
        await self._store.async_save(self._snapshot())

    def _sun(self, day: dt.date, event: str) -> dt.datetime | None:
        return get_astral_event_date(self.hass, event, day)

    # --- persistence ---

    def _snapshot(self) -> dict[str, Any]:
        return {
            "global_enabled": self.global_enabled,
            "groups": {
                subentry_id: runtime.as_store()
                for subentry_id, runtime in self.groups.items()
            },
        }

    @callback
    def async_schedule_save(self) -> None:
        self._store.async_delay_save(self._snapshot, SAVE_DELAY_SECONDS)

    # --- explicit turn-on detection (spec §7.4) ---

    @callback
    def _async_on_call_service(self, event: Event) -> None:
        data = event.data
        if data.get(ATTR_DOMAIN) != LIGHT_DOMAIN or not is_explicit_turn_on(
            data.get(ATTR_SERVICE, ""), data.get(ATTR_SERVICE_DATA) or {}
        ):
            return
        now = dt_util.utcnow()
        cutoff = now - dt.timedelta(seconds=EXPLICIT_CONTEXT_SECONDS)
        self._explicit = {
            context_id: at for context_id, at in self._explicit.items() if at > cutoff
        }
        self._explicit[event.context.id] = now

    def is_explicit_context(self, context_id: str | None) -> bool:
        """Was this context a recent light.turn_on/toggle that set values?"""
        at = self._explicit.get(context_id) if context_id else None
        return at is not None and dt_util.utcnow() - at <= dt.timedelta(
            seconds=EXPLICIT_CONTEXT_SECONDS
        )

    # --- global controls (spec §8) ---

    async def async_set_global_enabled(self, enabled: bool) -> None:
        was_active = {sid for sid, runtime in self.groups.items() if runtime.active}
        self.global_enabled = enabled
        for subentry_id, runtime in self.groups.items():
            if runtime.active and subentry_id not in was_active:
                await runtime.async_activate()
        self.async_schedule_save()
        self._notify()

    async def async_press_all(self, phase: Phase) -> None:
        """Global Day now / Night now: every group whose own switch is on."""
        await asyncio.gather(
            *(
                runtime.async_press(phase)
                for runtime in self.groups.values()
                if runtime.enabled
            )
        )

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
```

Replace `custom_components/light_manager/__init__.py` with:

```python
"""Light Manager: day/night brightness and color temperature for light groups."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import Manager

type LightManagerConfigEntry = ConfigEntry[Manager]

PLATFORMS: list[Platform] = []


async def async_setup_entry(
    hass: HomeAssistant, entry: LightManagerConfigEntry
) -> bool:
    """Start the manager for the parent entry and all group subentries."""
    manager = Manager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: LightManagerConfigEntry) -> None:
    """Spec §10: any entry or subentry change reloads everything."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: LightManagerConfigEntry
) -> bool:
    """Stop timers and listeners and save state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q`
Expected: `131 passed`.

- [ ] **Step 6: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add custom_components/light_manager tests
git commit -m "Add runtime: group scheduling, override tracking and persistence"
```

---

### Task 6: Config flow (groups, reconfigure menu, customize a light)

**Files:**
- Modify: `custom_components/light_manager/config_flow.py` (full replacement)
- Create: `custom_components/light_manager/strings.json`, `custom_components/light_manager/translations/en.json` (identical)
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes:
  - `members.expand_lights`, `schedule.fixed_targets_valid`, `curve.capabilities_from_attributes`
  - the `const` keys and defaults
- Produces:
  - `LightManagerConfigFlow.async_get_supported_subentry_types` → `{"group": GroupSubentryFlow}`.
  - `GroupSubentryFlow` steps:
    - `user` → `timing` (add).
    - `reconfigure` (menu) → `settings` → `timing` | `customize` → `customize_light`.
  - Saved data follows spec §5.5 exactly.
  - Error keys: `name_required`, `name_taken`, `no_lights`, `light_in_other_group` (placeholder `{conflicts}`), `transition_too_long`.
  - Abort keys: `reconfigure_successful`, `no_lights_to_customize`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_flow.py`:

```python
"""Config flow: parent entry, group subentries, reconfigure and customize (§5)."""

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.light_manager.const import DOMAIN

from .common import FakeLights, group_data
from .conftest import SetupIntegration

SETTINGS = {
    "name": "Bedroom",
    "lights": ["light.bed"],
    "day_brightness_pct": 90.0,  # selectors return floats
    "day_color_temp_kelvin": 3800.0,
    "day_target": "sun",
    "night_brightness_pct": 10.0,
    "night_color_temp_kelvin": 2000.0,
    "night_target": "fixed",
    "transition_min": 45.0,
    "off_behavior": "stay_overridden",
}


def suggested(result: FlowResult) -> dict[str, Any]:
    return {
        str(key): (key.description or {}).get("suggested_value")
        for key in result["data_schema"].schema
    }


async def start_add(hass: HomeAssistant, entry: ConfigEntry) -> FlowResult:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "group"), context={"source": SOURCE_USER}
    )


async def start_reconfigure(hass: HomeAssistant, entry: ConfigEntry) -> FlowResult:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "group"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "group_1"},
    )


async def configure(hass: HomeAssistant, result: FlowResult, data: dict) -> FlowResult:
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


@pytest.fixture
async def entry(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> ConfigEntry:
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    lights.add_color_temp("light.bed")
    return await setup_integration(group_data())


async def test_parent_entry_is_created_without_questions(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Light Manager"
    assert result["data"] == {}

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "single_instance_allowed"


async def test_add_group_with_defaults_suggested(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    result = await start_add(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert suggested(result) == {
        "name": None,
        "lights": None,
        "day_brightness_pct": 100,
        "day_color_temp_kelvin": 4000,
        "day_target": "sun",
        "night_brightness_pct": 20,
        "night_color_temp_kelvin": 2200,
        "night_target": "sun",
        "transition_min": 30,
        "off_behavior": "return_to_auto",
    }

    result = await configure(hass, result, SETTINGS)
    assert result["step_id"] == "timing"
    # Only the fields for the chosen target types (sunrise offset, night time).
    assert suggested(result) == {"day_offset_min": 0, "night_time": "21:00:00"}

    result = await configure(
        hass, result, {"day_offset_min": -15.0, "night_time": "22:30:00"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom"
    assert result["data"] == {
        "name": "Bedroom",
        "lights": ["light.bed"],
        "day": {"brightness_pct": 90, "color_temp_kelvin": 3800},
        "night": {"brightness_pct": 10, "color_temp_kelvin": 2000},
        "day_target": {"type": "sun", "offset_min": -15},
        "night_target": {"type": "fixed", "time": "22:30:00"},
        "transition_min": 45,
        "off_behavior": "stay_overridden",
        "light_overrides": {},
    }
    # Adding the subentry reloads the integration, which starts the new group.
    await hass.async_block_till_done()
    new_id = next(sid for sid in entry.subentries if sid != "group_1")
    assert set(entry.runtime_data.groups) == {"group_1", new_id}


async def add_helper(hass: HomeAssistant, members: list[str]) -> str:
    helper = er.async_get(hass).async_get_or_create(
        "light", "group", "downstairs", suggested_object_id="downstairs"
    )
    hass.states.async_set(helper.entity_id, "on", {"entity_id": members})
    return helper.entity_id


@pytest.mark.parametrize(
    ("changes", "field", "error"),
    [
        ({"name": "   "}, "name", "name_required"),
        ({"name": "living ROOM"}, "name", "name_taken"),
        ({"lights": []}, "lights", "no_lights"),
        ({"lights": ["light.bed", "light.dimmer"]}, "lights", "light_in_other_group"),
    ],
)
async def test_settings_validation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    changes: dict[str, Any],
    field: str,
    error: str,
) -> None:
    result = await start_add(hass, entry)

    result = await configure(hass, result, SETTINGS | changes)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {field: error}
    # The form keeps what the user typed.
    assert suggested(result)["night_brightness_pct"] == 10.0


async def test_light_in_another_group_through_a_helper(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    helper = await add_helper(hass, ["light.bed", "light.lamp"])
    result = await start_add(hass, entry)

    result = await configure(hass, result, SETTINGS | {"lights": [helper]})

    assert result["errors"] == {"lights": "light_in_other_group"}
    assert result["description_placeholders"]["conflicts"] == "light.lamp"


@pytest.mark.parametrize(
    ("day_time", "night_time", "transition", "ok"),
    [
        ("07:00:00", "07:20:00", 30, False),
        ("21:00:00", "21:00:00", 0, False),
        ("23:50:00", "00:10:00", 30, False),  # gap across midnight
        ("07:00:00", "07:30:00", 30, True),
    ],
)
async def test_fixed_targets_must_leave_room_for_the_transition(
    hass: HomeAssistant,
    entry: ConfigEntry,
    day_time: str,
    night_time: str,
    transition: int,
    ok: bool,
) -> None:
    result = await start_add(hass, entry)
    result = await configure(
        hass,
        result,
        SETTINGS | {"day_target": "fixed", "transition_min": float(transition)},
    )

    result = await configure(
        hass, result, {"day_time": day_time, "night_time": night_time}
    )

    if ok:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["step_id"] == "timing"
        assert result["errors"] == {"base": "transition_too_long"}


async def test_reconfigure_menu_edits_settings_and_drops_stale_overrides(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> None:
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    overrides = {
        "light.lamp": {"day_brightness_pct": 80},
        "light.dimmer": {"night_brightness_pct": 5},
    }
    entry = await setup_integration(group_data(light_overrides=overrides))

    result = await start_reconfigure(hass, entry)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["settings", "customize"]

    result = await configure(hass, result, {"next_step_id": "settings"})
    assert result["step_id"] == "settings"
    assert suggested(result)["name"] == "Living room"
    assert suggested(result)["night_target"] == "fixed"

    form = suggested(result) | {
        "name": "Living room",  # unchanged name is not "taken"
        "lights": ["light.dimmer"],
        "night_target": "sun",
    }
    result = await configure(hass, result, form)
    assert suggested(result) == {"day_time": "07:00:00", "night_offset_min": 0}

    result = await configure(
        hass, result, {"day_time": "06:45:00", "night_offset_min": 20.0}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    data = entry.subentries["group_1"].data
    assert data["lights"] == ["light.dimmer"]
    assert data["day_target"] == {"type": "fixed", "time": "06:45:00"}
    assert data["night_target"] == {"type": "sun", "offset_min": 20}
    assert data["light_overrides"] == {"light.dimmer": {"night_brightness_pct": 5}}


async def test_rename_updates_the_subentry_title(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    result = await start_reconfigure(hass, entry)
    result = await configure(hass, result, {"next_step_id": "settings"})
    result = await configure(hass, result, suggested(result) | {"name": "Den"})
    result = await configure(hass, result, suggested(result))

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["group_1"].title == "Den"


async def test_customize_a_light(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> None:
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    overrides = {"light.lamp": {"day_brightness_pct": 80}}
    entry = await setup_integration(group_data(light_overrides=overrides))

    result = await start_reconfigure(hass, entry)
    result = await configure(hass, result, {"next_step_id": "customize"})
    assert result["step_id"] == "customize"
    selector = result["data_schema"].schema["light"]
    assert selector.config["options"] == [
        {"value": "light.lamp", "label": "lamp (customized)"},
        {"value": "light.dimmer", "label": "dimmer"},
    ]

    result = await configure(hass, result, {"light": "light.dimmer"})
    assert result["step_id"] == "customize_light"
    # Brightness only: the dimmer has no color temperature.
    assert suggested(result) == {
        "day_brightness_pct": None,
        "night_brightness_pct": None,
    }
    assert result["description_placeholders"] == {
        "light": "dimmer",
        "day": "100%, 4000 K",
        "night": "20%, 2200 K",
    }

    result = await configure(hass, result, {"night_brightness_pct": 5.0})

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["group_1"].data["light_overrides"] == {
        "light.lamp": {"day_brightness_pct": 80},
        "light.dimmer": {"night_brightness_pct": 5},
    }


async def test_clearing_every_field_removes_the_customization(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> None:
    lights.add_color_temp("light.lamp")
    overrides = {
        "light.lamp": {"day_brightness_pct": 80, "night_color_temp_kelvin": 1800}
    }
    entry = await setup_integration(
        group_data(lights=["light.lamp"], light_overrides=overrides)
    )
    result = await start_reconfigure(hass, entry)
    result = await configure(hass, result, {"next_step_id": "customize"})
    result = await configure(hass, result, {"light": "light.lamp"})
    assert suggested(result) == {
        "day_brightness_pct": 80,
        "day_color_temp_kelvin": None,
        "night_brightness_pct": None,
        "night_color_temp_kelvin": 1800,
    }

    result = await configure(hass, result, {})

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["group_1"].data["light_overrides"] == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_config_flow.py -q`
Expected: `14 failed, 1 passed`. Each failure is `homeassistant.data_entry_flow.UnknownHandler: Config entry 'light_manager' does not support subentry 'group'`. Only `test_parent_entry_is_created_without_questions` passes.

- [ ] **Step 3: Implement the flow and its text**

Replace `custom_components/light_manager/config_flow.py` with:

```python
"""Config flow for Light Manager: the parent entry and light-group subentries."""

from __future__ import annotations

import datetime as dt
from typing import Any

import voluptuous as vol
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    ColorTempSelector,
    ColorTempSelectorConfig,
    ColorTempSelectorUnit,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
    CONF_BRIGHTNESS_PCT,
    CONF_COLOR_TEMP_KELVIN,
    CONF_DAY,
    CONF_DAY_TARGET,
    CONF_LIGHT_OVERRIDES,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_NIGHT,
    CONF_NIGHT_TARGET,
    CONF_OFF_BEHAVIOR,
    CONF_OFFSET_MIN,
    CONF_TIME,
    CONF_TRANSITION_MIN,
    CONF_TYPE,
    DEFAULT_DAY_BRIGHTNESS_PCT,
    DEFAULT_DAY_COLOR_TEMP_KELVIN,
    DEFAULT_DAY_TIME,
    DEFAULT_NIGHT_BRIGHTNESS_PCT,
    DEFAULT_NIGHT_COLOR_TEMP_KELVIN,
    DEFAULT_NIGHT_TIME,
    DEFAULT_TRANSITION_MIN,
    DOMAIN,
    MAX_BRIGHTNESS_PCT,
    MAX_KELVIN,
    MAX_OFFSET_MIN,
    MAX_TRANSITION_MIN,
    MIN_BRIGHTNESS_PCT,
    MIN_KELVIN,
    OFF_RETURN_TO_AUTO,
    OFF_STAY_OVERRIDDEN,
    OVERRIDE_KEYS,
    SUBENTRY_TYPE_GROUP,
    TARGET_FIXED,
    TARGET_SUN,
)
from .curve import capabilities_from_attributes
from .members import expand_lights
from .schedule import fixed_targets_valid

# Flat form keys; stored data nests them (spec §5.5).
DAY_BRIGHTNESS = "day_brightness_pct"
DAY_KELVIN = "day_color_temp_kelvin"
NIGHT_BRIGHTNESS = "night_brightness_pct"
NIGHT_KELVIN = "night_color_temp_kelvin"
DAY_OFFSET = "day_offset_min"
DAY_TIME = "day_time"
NIGHT_OFFSET = "night_offset_min"
NIGHT_TIME = "night_time"
CONF_LIGHT = "light"

SETTINGS_DEFAULTS: dict[str, Any] = {
    DAY_BRIGHTNESS: DEFAULT_DAY_BRIGHTNESS_PCT,
    DAY_KELVIN: DEFAULT_DAY_COLOR_TEMP_KELVIN,
    CONF_DAY_TARGET: TARGET_SUN,
    NIGHT_BRIGHTNESS: DEFAULT_NIGHT_BRIGHTNESS_PCT,
    NIGHT_KELVIN: DEFAULT_NIGHT_COLOR_TEMP_KELVIN,
    CONF_NIGHT_TARGET: TARGET_SUN,
    CONF_TRANSITION_MIN: DEFAULT_TRANSITION_MIN,
    CONF_OFF_BEHAVIOR: OFF_RETURN_TO_AUTO,
}
TIMING_DEFAULTS: dict[str, Any] = {
    DAY_OFFSET: 0,
    DAY_TIME: DEFAULT_DAY_TIME,
    NIGHT_OFFSET: 0,
    NIGHT_TIME: DEFAULT_NIGHT_TIME,
}


def _brightness() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_BRIGHTNESS_PCT,
            max=MAX_BRIGHTNESS_PCT,
            step=1,
            unit_of_measurement="%",
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _kelvin() -> ColorTempSelector:
    return ColorTempSelector(
        ColorTempSelectorConfig(
            unit=ColorTempSelectorUnit.KELVIN, min=MIN_KELVIN, max=MAX_KELVIN
        )
    )


def _minutes(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement="min",
            mode=NumberSelectorMode.BOX,
        )
    )


def _choice(key: str, options: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options, mode=SelectSelectorMode.LIST, translation_key=key
        )
    )


SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_LIGHTS): EntitySelector(
            EntitySelectorConfig(domain=LIGHT_DOMAIN, multiple=True)
        ),
        vol.Required(DAY_BRIGHTNESS): _brightness(),
        vol.Required(DAY_KELVIN): _kelvin(),
        vol.Required(CONF_DAY_TARGET): _choice(
            CONF_DAY_TARGET, [TARGET_SUN, TARGET_FIXED]
        ),
        vol.Required(NIGHT_BRIGHTNESS): _brightness(),
        vol.Required(NIGHT_KELVIN): _kelvin(),
        vol.Required(CONF_NIGHT_TARGET): _choice(
            CONF_NIGHT_TARGET, [TARGET_SUN, TARGET_FIXED]
        ),
        vol.Required(CONF_TRANSITION_MIN): _minutes(0, MAX_TRANSITION_MIN),
        vol.Required(CONF_OFF_BEHAVIOR): _choice(
            CONF_OFF_BEHAVIOR, [OFF_RETURN_TO_AUTO, OFF_STAY_OVERRIDDEN]
        ),
    }
)


def _timing_schema(day_type: str, night_type: str) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {}
    for kind_type, offset_key, time_key in (
        (day_type, DAY_OFFSET, DAY_TIME),
        (night_type, NIGHT_OFFSET, NIGHT_TIME),
    ):
        if kind_type == TARGET_SUN:
            fields[vol.Required(offset_key)] = _minutes(-MAX_OFFSET_MIN, MAX_OFFSET_MIN)
        else:
            fields[vol.Required(time_key)] = TimeSelector()
    return vol.Schema(fields)


def _override_schema(color_temp: bool) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {vol.Optional(DAY_BRIGHTNESS): _brightness()}
    if color_temp:
        fields[vol.Optional(DAY_KELVIN)] = _kelvin()
    fields[vol.Optional(NIGHT_BRIGHTNESS)] = _brightness()
    if color_temp:
        fields[vol.Optional(NIGHT_KELVIN)] = _kelvin()
    return vol.Schema(fields)


def _form_values(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split stored subentry data into step 1 and step 2 form values."""
    day, night = data[CONF_DAY], data[CONF_NIGHT]
    day_target, night_target = data[CONF_DAY_TARGET], data[CONF_NIGHT_TARGET]
    settings = {
        CONF_NAME: data[CONF_NAME],
        CONF_LIGHTS: data[CONF_LIGHTS],
        DAY_BRIGHTNESS: day[CONF_BRIGHTNESS_PCT],
        DAY_KELVIN: day[CONF_COLOR_TEMP_KELVIN],
        CONF_DAY_TARGET: day_target[CONF_TYPE],
        NIGHT_BRIGHTNESS: night[CONF_BRIGHTNESS_PCT],
        NIGHT_KELVIN: night[CONF_COLOR_TEMP_KELVIN],
        CONF_NIGHT_TARGET: night_target[CONF_TYPE],
        CONF_TRANSITION_MIN: data[CONF_TRANSITION_MIN],
        CONF_OFF_BEHAVIOR: data[CONF_OFF_BEHAVIOR],
    }
    timing = dict(TIMING_DEFAULTS)
    for target, offset_key, time_key in (
        (day_target, DAY_OFFSET, DAY_TIME),
        (night_target, NIGHT_OFFSET, NIGHT_TIME),
    ):
        if target[CONF_TYPE] == TARGET_SUN:
            timing[offset_key] = target.get(CONF_OFFSET_MIN, 0)
        else:
            timing[time_key] = target[CONF_TIME]
    return settings, timing


def _target(kind_type: str, offset: Any, time: Any) -> dict[str, Any]:
    if kind_type == TARGET_SUN:
        return {CONF_TYPE: TARGET_SUN, CONF_OFFSET_MIN: int(offset)}
    return {CONF_TYPE: TARGET_FIXED, CONF_TIME: time}


class LightManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """The parent entry: created with no questions (spec §5.2)."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_GROUP: GroupSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(title="Light Manager", data={})


class GroupSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a light group (spec §5.3, §5.4)."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}
        self._timing: dict[str, Any] = dict(TIMING_DEFAULTS)
        self._light: str | None = None

    # Add: step 1 -> timing.

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_settings("user", user_input, SETTINGS_DEFAULTS)

    # Reconfigure: menu -> (settings -> timing) | (customize -> customize_light).

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        settings, self._timing = _form_values(
            dict(self._get_reconfigure_subentry().data)
        )
        self._settings = settings
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["settings", "customize"],
            description_placeholders={"name": settings[CONF_NAME]},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_settings("settings", user_input, self._settings)

    async def _async_settings(
        self, step_id: str, user_input: dict[str, Any] | None, suggested: dict[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"conflicts": ""}
        if user_input is not None:
            user_input[CONF_NAME] = user_input[CONF_NAME].strip()
            errors, placeholders["conflicts"] = self._validate_settings(user_input)
            if not errors:
                self._settings = user_input
                return await self.async_step_timing()
            suggested = user_input
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(SETTINGS_SCHEMA, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _validate_settings(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], str]:
        name = user_input[CONF_NAME]
        if not name:
            return {CONF_NAME: "name_required"}, ""
        own_id = None if self.source == SOURCE_USER else self._reconfigure_subentry_id
        others = [
            sub
            for sub_id, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUBENTRY_TYPE_GROUP and sub_id != own_id
        ]
        if any(sub.data[CONF_NAME].casefold() == name.casefold() for sub in others):
            return {CONF_NAME: "name_taken"}, ""
        if not user_input[CONF_LIGHTS]:
            return {CONF_LIGHTS: "no_lights"}, ""
        mine, _ = expand_lights(self.hass, user_input[CONF_LIGHTS])
        taken: set[str] = set()
        for sub in others:
            taken.update(expand_lights(self.hass, sub.data[CONF_LIGHTS])[0])
        if conflicts := [light for light in mine if light in taken]:
            return {CONF_LIGHTS: "light_in_other_group"}, ", ".join(conflicts)
        return {}, ""

    async def async_step_timing(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        settings = self._settings
        day_type, night_type = settings[CONF_DAY_TARGET], settings[CONF_NIGHT_TARGET]
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                day_type == TARGET_FIXED
                and night_type == TARGET_FIXED
                and not fixed_targets_valid(
                    dt.time.fromisoformat(user_input[DAY_TIME]),
                    dt.time.fromisoformat(user_input[NIGHT_TIME]),
                    dt.timedelta(minutes=int(settings[CONF_TRANSITION_MIN])),
                )
            ):
                errors["base"] = "transition_too_long"
            else:
                return self._async_save(user_input)
        return self.async_show_form(
            step_id="timing",
            data_schema=self.add_suggested_values_to_schema(
                _timing_schema(day_type, night_type), user_input or self._timing
            ),
            errors=errors,
        )

    @callback
    def _async_save(self, timing: dict[str, Any]) -> SubentryFlowResult:
        settings = self._settings
        lights = list(settings[CONF_LIGHTS])
        overrides: dict[str, Any] = {}
        if self.source != SOURCE_USER:
            bulbs = set(expand_lights(self.hass, lights)[0])
            current = self._get_reconfigure_subentry().data[CONF_LIGHT_OVERRIDES]
            overrides = {eid: o for eid, o in current.items() if eid in bulbs}
        data = {
            CONF_NAME: settings[CONF_NAME],
            CONF_LIGHTS: lights,
            CONF_DAY: {
                CONF_BRIGHTNESS_PCT: int(settings[DAY_BRIGHTNESS]),
                CONF_COLOR_TEMP_KELVIN: int(settings[DAY_KELVIN]),
            },
            CONF_NIGHT: {
                CONF_BRIGHTNESS_PCT: int(settings[NIGHT_BRIGHTNESS]),
                CONF_COLOR_TEMP_KELVIN: int(settings[NIGHT_KELVIN]),
            },
            CONF_DAY_TARGET: _target(
                settings[CONF_DAY_TARGET], timing.get(DAY_OFFSET), timing.get(DAY_TIME)
            ),
            CONF_NIGHT_TARGET: _target(
                settings[CONF_NIGHT_TARGET],
                timing.get(NIGHT_OFFSET),
                timing.get(NIGHT_TIME),
            ),
            CONF_TRANSITION_MIN: int(settings[CONF_TRANSITION_MIN]),
            CONF_OFF_BEHAVIOR: settings[CONF_OFF_BEHAVIOR],
            CONF_LIGHT_OVERRIDES: overrides,
        }
        if self.source == SOURCE_USER:
            return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            title=data[CONF_NAME],
            data=data,
        )

    async def async_step_customize(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        data = self._get_reconfigure_subentry().data
        bulbs, _ = expand_lights(self.hass, data[CONF_LIGHTS])
        if not bulbs:
            return self.async_abort(reason="no_lights_to_customize")
        if user_input is not None:
            self._light = user_input[CONF_LIGHT]
            return await self.async_step_customize_light()
        overrides = data[CONF_LIGHT_OVERRIDES]
        options = [
            SelectOptionDict(value=eid, label=self._label(eid, eid in overrides))
            for eid in bulbs
        ]
        return self.async_show_form(
            step_id="customize",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LIGHT): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    def _label(self, entity_id: str, customized: bool) -> str:
        state = self.hass.states.get(entity_id)
        name = state.name if state else entity_id
        return f"{name} (customized)" if customized else name

    async def async_step_customize_light(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        assert self._light is not None
        entry, subentry = self._get_entry(), self._get_reconfigure_subentry()
        overrides = dict(subentry.data[CONF_LIGHT_OVERRIDES])
        if user_input is not None:
            values = {
                key: int(user_input[key])
                for key in OVERRIDE_KEYS
                if user_input.get(key) is not None
            }
            if values:
                overrides[self._light] = values
            else:
                overrides.pop(self._light, None)
            return self.async_update_and_abort(
                entry,
                subentry,
                data={**subentry.data, CONF_LIGHT_OVERRIDES: overrides},
            )
        state = self.hass.states.get(self._light)
        color_temp = (
            state is None
            or capabilities_from_attributes(state.attributes).any_color_temp
        )
        settings = self._settings
        return self.async_show_form(
            step_id="customize_light",
            data_schema=self.add_suggested_values_to_schema(
                _override_schema(color_temp), overrides.get(self._light, {})
            ),
            description_placeholders={
                "light": self._label(self._light, customized=False),
                "day": f"{settings[DAY_BRIGHTNESS]}%, {settings[DAY_KELVIN]} K",
                "night": f"{settings[NIGHT_BRIGHTNESS]}%, {settings[NIGHT_KELVIN]} K",
            },
        )
```

Create `custom_components/light_manager/strings.json`, and an identical copy at `custom_components/light_manager/translations/en.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Light Manager",
        "description": "Light Manager has no settings of its own. After adding it, add a light group."
      }
    },
    "abort": {
      "single_instance_allowed": "Light Manager is already set up. Add light groups to it instead."
    }
  },
  "config_subentries": {
    "group": {
      "entry_type": "Light group",
      "initiate_flow": {
        "user": "Add light group",
        "reconfigure": "Reconfigure light group"
      },
      "step": {
        "user": {
          "title": "Add light group (step 1 of 2)",
          "description": "Pick the lights and their day and night settings. Timing details come next.",
          "data": {
            "name": "Name",
            "lights": "Lights",
            "day_brightness_pct": "Day brightness",
            "day_color_temp_kelvin": "Day color temperature",
            "day_target": "Day starts at",
            "night_brightness_pct": "Night brightness",
            "night_color_temp_kelvin": "Night color temperature",
            "night_target": "Night starts at",
            "transition_min": "Transition",
            "off_behavior": "When an overridden light is turned off"
          },
          "data_description": {
            "name": "Used for the group's device and entity names.",
            "lights": "Light groups (helpers) are expanded into their member lights.",
            "day_target": "The lights reach the day settings at this time.",
            "night_target": "The lights reach the night settings at this time.",
            "transition_min": "Minutes the lights take to change between day and night. The change ends at the target time. 0 switches instantly.",
            "off_behavior": "A light you change by hand stops following the schedule until it is turned off and on again, or until the next transition starts."
          }
        },
        "settings": {
          "title": "Edit group settings (step 1 of 2)",
          "description": "Change the lights and their day and night settings. Timing details come next.",
          "data": {
            "name": "Name",
            "lights": "Lights",
            "day_brightness_pct": "Day brightness",
            "day_color_temp_kelvin": "Day color temperature",
            "day_target": "Day starts at",
            "night_brightness_pct": "Night brightness",
            "night_color_temp_kelvin": "Night color temperature",
            "night_target": "Night starts at",
            "transition_min": "Transition",
            "off_behavior": "When an overridden light is turned off"
          },
          "data_description": {
            "name": "Used for the group's device and entity names.",
            "lights": "Light groups (helpers) are expanded into their member lights.",
            "day_target": "The lights reach the day settings at this time.",
            "night_target": "The lights reach the night settings at this time.",
            "transition_min": "Minutes the lights take to change between day and night. The change ends at the target time. 0 switches instantly.",
            "off_behavior": "A light you change by hand stops following the schedule until it is turned off and on again, or until the next transition starts."
          }
        },
        "timing": {
          "title": "Timing (step 2 of 2)",
          "data": {
            "day_offset_min": "Sunrise offset",
            "day_time": "Day time",
            "night_offset_min": "Sunset offset",
            "night_time": "Night time"
          },
          "data_description": {
            "day_offset_min": "Minutes after sunrise. Negative is earlier.",
            "night_offset_min": "Minutes after sunset. Negative is earlier."
          }
        },
        "reconfigure": {
          "title": "Reconfigure {name}",
          "menu_options": {
            "settings": "Edit group settings",
            "customize": "Customize a light"
          }
        },
        "customize": {
          "title": "Customize a light",
          "description": "Pick a light to give its own brightness or color temperature.",
          "data": {
            "light": "Light"
          }
        },
        "customize_light": {
          "title": "Customize {light}",
          "description": "Leave a field blank to follow the group (day: {day}; night: {night}). Clear every field to remove the customization.",
          "data": {
            "day_brightness_pct": "Day brightness",
            "day_color_temp_kelvin": "Day color temperature",
            "night_brightness_pct": "Night brightness",
            "night_color_temp_kelvin": "Night color temperature"
          }
        }
      },
      "error": {
        "name_required": "Enter a name.",
        "name_taken": "Another group already has this name.",
        "no_lights": "Pick at least one light.",
        "light_in_other_group": "Already in another group: {conflicts}",
        "transition_too_long": "The transition is longer than the gap between the day and night targets."
      },
      "abort": {
        "reconfigure_successful": "The group was updated.",
        "no_lights_to_customize": "This group has no lights to customize yet."
      }
    }
  },
  "selector": {
    "day_target": {
      "options": {
        "sun": "Sunrise",
        "fixed": "Fixed time"
      }
    },
    "night_target": {
      "options": {
        "sun": "Sunset",
        "fixed": "Fixed time"
      }
    },
    "off_behavior": {
      "options": {
        "return_to_auto": "Return to automatic",
        "stay_overridden": "Stay overridden"
      }
    }
  }
}
```

Run: `mkdir -p custom_components/light_manager/translations && cp custom_components/light_manager/strings.json custom_components/light_manager/translations/en.json`

Notes:
- `config.step.user` exists only because hassfest requires a `config.step` block for config-flow integrations. The parent flow never shows that form.
- Menu option labels go under `step.reconfigure.menu_options`. Select-option labels go under the top-level `selector` key.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: `146 passed`.

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add custom_components/light_manager tests/test_config_flow.py
git commit -m "Add group config flow with reconfigure menu and per-light customization"
```

---

### Task 7: Entities (switches, buttons, phase sensor)

**Files:**
- Create: `custom_components/light_manager/entity.py`, `switch.py`, `button.py`, `sensor.py`, `icons.json`
- Modify: `custom_components/light_manager/__init__.py` (full replacement: `PLATFORMS` now lists button, sensor, switch)
- Modify: `custom_components/light_manager/strings.json` and `translations/en.json` (full replacement: adds the `entity` section)
- Test: `tests/test_entities.py`

**Interfaces:**
- Consumes:
  - `Manager`: `entry`, `global_enabled`, `groups`, `async_set_global_enabled`, `async_press_all`, `async_add_listener`.
  - `GroupRuntime`: `subentry_id`, `config.name`, `enabled`, `async_set_enabled`, `async_press`, `phase_state`, `async_add_listener`.
- Produces: the entities in spec §8.
  - Unique IDs: `{entry_id}_{key}` (global) and `{subentry_id}_{key}` (group). Keys: `automatic`, `day_now`, `night_now`, `phase`.
  - Group entities are added with `config_subentry_id=subentry_id`.
  - Group entities keep the runtime in `self.runtime`, **not** `self.group`: HA 2026's `Entity.group` is reserved for entity groups. Shadowing it logs a deprecation that becomes an error in HA 2027.2. `test_entity_ids_unique_ids_and_devices` fails on any such report.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entities.py`:

```python
"""Entities: IDs, devices, switch/button semantics and the phase sensor (§8)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.light_manager.const import DOMAIN

from .common import ENTRY_ID, FakeLights, advance_to, group_data, local
from .conftest import SetupIntegration

NOON = local(2026, 9, 30, 12, 0)
GROUP_ENTITIES = {
    "switch.living_room_automatic": "group_1_automatic",
    "button.living_room_day_now": "group_1_day_now",
    "button.living_room_night_now": "group_1_night_now",
    "sensor.living_room_phase": "group_1_phase",
}
GLOBAL_ENTITIES = {
    "switch.light_manager_automatic": f"{ENTRY_ID}_automatic",
    "button.light_manager_day_now": f"{ENTRY_ID}_day_now",
    "button.light_manager_night_now": f"{ENTRY_ID}_night_now",
}


async def start(
    hass: HomeAssistant,
    freezer,
    lights: FakeLights,
    setup_integration: SetupIntegration,
    *groups: dict,
):
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    lights.add_dimmer("light.porch")
    entry = await setup_integration(*(groups or (group_data(),)))
    lights.clear()
    return entry


async def call(hass: HomeAssistant, domain: str, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_entity_ids_unique_ids_and_devices(
    hass: HomeAssistant, freezer, lights, setup_integration, caplog
) -> None:
    await start(hass, freezer, lights, setup_integration)
    # HA's frame helper reports deprecated usage, e.g. shadowing Entity.group.
    assert "Detected that" not in caplog.text
    entities = er.async_get(hass)
    devices = dr.async_get(hass)

    for entity_id, unique_id in (GLOBAL_ENTITIES | GROUP_ENTITIES).items():
        entity = entities.async_get(entity_id)
        assert entity is not None, entity_id
        assert entity.unique_id == unique_id
    assert entities.async_get("sensor.light_manager_phase") is None

    group_device = devices.async_get_device_by_identifier((DOMAIN, "group_1"), ENTRY_ID)
    assert group_device.name == "Living room"
    assert group_device.config_entries_subentries == {ENTRY_ID: {"group_1"}}
    global_device = devices.async_get_device_by_identifier((DOMAIN, ENTRY_ID), ENTRY_ID)
    assert global_device.name == "Light Manager"
    assert global_device.config_entries_subentries == {ENTRY_ID: {None}}
    for entity_id in GROUP_ENTITIES:
        assert entities.async_get(entity_id).config_subentry_id == "group_1"


async def test_renaming_a_group_keeps_entity_ids(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries["group_1"],
        title="Den",
        data=group_data(name="Den"),
    )
    await hass.async_block_till_done()

    for entity_id in GROUP_ENTITIES:
        assert hass.states.get(entity_id) is not None, entity_id
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "group_1"), ENTRY_ID
    )
    assert device.name == "Den"


async def test_group_switch(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    group = entry.runtime_data.groups["group_1"]
    assert hass.states.get("switch.living_room_automatic").state == "on"

    await call(hass, "switch", "turn_off", "switch.living_room_automatic")

    assert hass.states.get("switch.living_room_automatic").state == "off"
    assert group.enabled is False
    assert group.active is False

    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))
    assert lights.calls == []
    # The sensor keeps showing the schedule while the group is inactive.
    assert hass.states.get("sensor.living_room_phase").state == "to_night"

    await call(hass, "switch", "turn_on", "switch.living_room_automatic")
    assert lights.calls_for("light.dimmer") == [{"brightness": 153, "transition": 2}]


async def test_global_switch(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    await call(hass, "switch", "turn_off", "switch.light_manager_automatic")

    assert hass.states.get("switch.light_manager_automatic").state == "off"
    # The group's own switch is unchanged, but the group is inactive.
    assert hass.states.get("switch.living_room_automatic").state == "on"
    assert entry.runtime_data.groups["group_1"].active is False

    await call(hass, "switch", "turn_on", "switch.light_manager_automatic")
    assert entry.runtime_data.groups["group_1"].active is True


async def test_group_button_and_sensor_attributes(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration)
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.state == "day"
    assert sensor.attributes["options"] == ["day", "to_night", "night", "to_day"]
    assert sensor.attributes["progress"] is None
    assert sensor.attributes["held"] is False
    assert sensor.attributes["next_day_target"] == "2026-10-01T14:00:00+00:00"
    assert sensor.attributes["next_night_target"] == "2026-10-01T04:00:00+00:00"
    assert sensor.attributes["overridden_lights"] == []

    await call(hass, "button", "press", "button.living_room_night_now")

    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.state == "night"
    assert sensor.attributes["held"] is True


async def test_sensor_follows_the_ramp_and_overrides(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration)

    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.state == "to_night"
    assert sensor.attributes["progress"] == 50

    freezer.tick(15)
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.attributes["overridden_lights"] == ["light.lamp"]


async def test_global_button_acts_on_groups_whose_switch_is_on(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    await start(
        hass,
        freezer,
        lights,
        setup_integration,
        group_data(),
        group_data(name="Porch", lights=["light.porch"]),
    )
    await call(hass, "switch", "turn_off", "switch.porch_automatic")
    await call(hass, "switch", "turn_off", "switch.light_manager_automatic")

    await call(hass, "button", "press", "button.light_manager_night_now")

    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]
    assert lights.calls_for("light.porch") == []
    assert hass.states.get("sensor.living_room_phase").attributes["held"] is True
    assert hass.states.get("sensor.porch_phase").attributes["held"] is False


async def test_switch_states_survive_a_reload(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    await call(hass, "switch", "turn_off", "switch.living_room_automatic")
    await call(hass, "switch", "turn_off", "switch.light_manager_automatic")

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("switch.living_room_automatic").state == "off"
    assert hass.states.get("switch.light_manager_automatic").state == "off"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_entities.py -q`
Expected: `8 failed`, because no entities exist yet. The errors include `AssertionError: switch.light_manager_automatic`, `ServiceNotFound: Action switch.turn_off not found` and `AttributeError: 'NoneType' object has no attribute 'state'`.

- [ ] **Step 3: Implement the entities**

Create `custom_components/light_manager/entity.py`:

```python
"""Base entities: the global Light Manager device and one device per group."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .group import GroupRuntime
from .manager import Manager


class GlobalEntity(Entity):
    """An entity on the global "Light Manager" device (spec §8)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: Manager, key: str) -> None:
        self.manager = manager
        entry_id = manager.entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Light Manager",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self.async_write_ha_state))


class GroupEntity(Entity):
    """An entity on a group's device. Unique IDs use the subentry ID, so
    renaming the group keeps entity IDs."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, group: GroupRuntime, key: str) -> None:
        self.runtime = group  # not .group: Entity.group is HA's entity groups
        self._attr_translation_key = key
        self._attr_unique_id = f"{group.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, group.subentry_id)},
            name=group.config.name,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))
```

Create `custom_components/light_manager/switch.py`:

```python
"""Enable switches: global and per group (spec §8)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LightManagerConfigEntry
from .entity import GlobalEntity, GroupEntity
from .group import GroupRuntime
from .manager import Manager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightManagerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities([GlobalSwitch(manager)])
    for subentry_id, group in manager.groups.items():
        async_add_entities([GroupSwitch(group)], config_subentry_id=subentry_id)


class GlobalSwitch(GlobalEntity, SwitchEntity):
    """Off: no group sends automatic commands."""

    def __init__(self, manager: Manager) -> None:
        super().__init__(manager, "automatic")

    @property
    def is_on(self) -> bool:
        return self.manager.global_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_set_global_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_set_global_enabled(False)


class GroupSwitch(GroupEntity, SwitchEntity):
    """Off: this group sends no automatic commands."""

    def __init__(self, group: GroupRuntime) -> None:
        super().__init__(group, "automatic")

    @property
    def is_on(self) -> bool:
        return self.runtime.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.runtime.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.runtime.async_set_enabled(False)
```

Create `custom_components/light_manager/button.py`:

```python
"""Day now / Night now buttons: global and per group (spec §6.5, §8)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LightManagerConfigEntry
from .entity import GlobalEntity, GroupEntity
from .group import GroupRuntime
from .manager import Manager
from .models import Phase

PARALLEL_UPDATES = 0

BUTTONS = {"day_now": Phase.DAY, "night_now": Phase.NIGHT}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightManagerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(GlobalButton(manager, key) for key in BUTTONS)
    for subentry_id, group in manager.groups.items():
        async_add_entities(
            (GroupButton(group, key) for key in BUTTONS),
            config_subentry_id=subentry_id,
        )


class GlobalButton(GlobalEntity, ButtonEntity):
    """Presses the button of every group whose own switch is on."""

    def __init__(self, manager: Manager, key: str) -> None:
        super().__init__(manager, key)
        self._phase = BUTTONS[key]

    async def async_press(self) -> None:
        await self.manager.async_press_all(self._phase)


class GroupButton(GroupEntity, ButtonEntity):
    """Applies the setpoint now and holds it until the next opposite ramp."""

    def __init__(self, group: GroupRuntime, key: str) -> None:
        super().__init__(group, key)
        self._phase = BUTTONS[key]

    async def async_press(self) -> None:
        await self.runtime.async_press(self._phase)
```

Create `custom_components/light_manager/sensor.py`:

```python
"""Phase sensor per group (spec §8)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LightManagerConfigEntry
from .entity import GroupEntity
from .group import GroupRuntime
from .models import Phase

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightManagerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, group in entry.runtime_data.groups.items():
        async_add_entities([PhaseSensor(group)], config_subentry_id=subentry_id)


class PhaseSensor(GroupEntity, SensorEntity):
    """The scheduled or held phase; shown even while the group is inactive."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, group: GroupRuntime) -> None:
        super().__init__(group, "phase")
        self._attr_options = [phase.value for phase in Phase]

    @property
    def native_value(self) -> str:
        return self.runtime.phase_state().phase.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.runtime.phase_state()
        return {
            "progress": state.progress,
            "held": state.held,
            "next_day_target": _iso(state.next_day_target),
            "next_night_target": _iso(state.next_night_target),
            "overridden_lights": state.overridden_lights,
        }


def _iso(moment: dt.datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()
```

Create `custom_components/light_manager/icons.json`:

```json
{
  "entity": {
    "button": {
      "day_now": {
        "default": "mdi:weather-sunny"
      },
      "night_now": {
        "default": "mdi:weather-night"
      }
    },
    "sensor": {
      "phase": {
        "default": "mdi:theme-light-dark",
        "state": {
          "day": "mdi:weather-sunny",
          "to_night": "mdi:weather-sunset-down",
          "night": "mdi:weather-night",
          "to_day": "mdi:weather-sunset-up"
        }
      }
    },
    "switch": {
      "automatic": {
        "default": "mdi:brightness-auto"
      }
    }
  }
}
```

Replace `custom_components/light_manager/__init__.py` with:

```python
"""Light Manager: day/night brightness and color temperature for light groups."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import Manager

type LightManagerConfigEntry = ConfigEntry[Manager]

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(
    hass: HomeAssistant, entry: LightManagerConfigEntry
) -> bool:
    """Start the manager for the parent entry and all group subentries."""
    manager = Manager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: LightManagerConfigEntry) -> None:
    """Spec §10: any entry or subentry change reloads everything."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: LightManagerConfigEntry
) -> bool:
    """Stop timers and listeners and save state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
```

Replace `custom_components/light_manager/strings.json` with the following, and copy it over `translations/en.json` again:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Light Manager",
        "description": "Light Manager has no settings of its own. After adding it, add a light group."
      }
    },
    "abort": {
      "single_instance_allowed": "Light Manager is already set up. Add light groups to it instead."
    }
  },
  "config_subentries": {
    "group": {
      "entry_type": "Light group",
      "initiate_flow": {
        "user": "Add light group",
        "reconfigure": "Reconfigure light group"
      },
      "step": {
        "user": {
          "title": "Add light group (step 1 of 2)",
          "description": "Pick the lights and their day and night settings. Timing details come next.",
          "data": {
            "name": "Name",
            "lights": "Lights",
            "day_brightness_pct": "Day brightness",
            "day_color_temp_kelvin": "Day color temperature",
            "day_target": "Day starts at",
            "night_brightness_pct": "Night brightness",
            "night_color_temp_kelvin": "Night color temperature",
            "night_target": "Night starts at",
            "transition_min": "Transition",
            "off_behavior": "When an overridden light is turned off"
          },
          "data_description": {
            "name": "Used for the group's device and entity names.",
            "lights": "Light groups (helpers) are expanded into their member lights.",
            "day_target": "The lights reach the day settings at this time.",
            "night_target": "The lights reach the night settings at this time.",
            "transition_min": "Minutes the lights take to change between day and night. The change ends at the target time. 0 switches instantly.",
            "off_behavior": "A light you change by hand stops following the schedule until it is turned off and on again, or until the next transition starts."
          }
        },
        "settings": {
          "title": "Edit group settings (step 1 of 2)",
          "description": "Change the lights and their day and night settings. Timing details come next.",
          "data": {
            "name": "Name",
            "lights": "Lights",
            "day_brightness_pct": "Day brightness",
            "day_color_temp_kelvin": "Day color temperature",
            "day_target": "Day starts at",
            "night_brightness_pct": "Night brightness",
            "night_color_temp_kelvin": "Night color temperature",
            "night_target": "Night starts at",
            "transition_min": "Transition",
            "off_behavior": "When an overridden light is turned off"
          },
          "data_description": {
            "name": "Used for the group's device and entity names.",
            "lights": "Light groups (helpers) are expanded into their member lights.",
            "day_target": "The lights reach the day settings at this time.",
            "night_target": "The lights reach the night settings at this time.",
            "transition_min": "Minutes the lights take to change between day and night. The change ends at the target time. 0 switches instantly.",
            "off_behavior": "A light you change by hand stops following the schedule until it is turned off and on again, or until the next transition starts."
          }
        },
        "timing": {
          "title": "Timing (step 2 of 2)",
          "data": {
            "day_offset_min": "Sunrise offset",
            "day_time": "Day time",
            "night_offset_min": "Sunset offset",
            "night_time": "Night time"
          },
          "data_description": {
            "day_offset_min": "Minutes after sunrise. Negative is earlier.",
            "night_offset_min": "Minutes after sunset. Negative is earlier."
          }
        },
        "reconfigure": {
          "title": "Reconfigure {name}",
          "menu_options": {
            "settings": "Edit group settings",
            "customize": "Customize a light"
          }
        },
        "customize": {
          "title": "Customize a light",
          "description": "Pick a light to give its own brightness or color temperature.",
          "data": {
            "light": "Light"
          }
        },
        "customize_light": {
          "title": "Customize {light}",
          "description": "Leave a field blank to follow the group (day: {day}; night: {night}). Clear every field to remove the customization.",
          "data": {
            "day_brightness_pct": "Day brightness",
            "day_color_temp_kelvin": "Day color temperature",
            "night_brightness_pct": "Night brightness",
            "night_color_temp_kelvin": "Night color temperature"
          }
        }
      },
      "error": {
        "name_required": "Enter a name.",
        "name_taken": "Another group already has this name.",
        "no_lights": "Pick at least one light.",
        "light_in_other_group": "Already in another group: {conflicts}",
        "transition_too_long": "The transition is longer than the gap between the day and night targets."
      },
      "abort": {
        "reconfigure_successful": "The group was updated.",
        "no_lights_to_customize": "This group has no lights to customize yet."
      }
    }
  },
  "selector": {
    "day_target": {
      "options": {
        "sun": "Sunrise",
        "fixed": "Fixed time"
      }
    },
    "night_target": {
      "options": {
        "sun": "Sunset",
        "fixed": "Fixed time"
      }
    },
    "off_behavior": {
      "options": {
        "return_to_auto": "Return to automatic",
        "stay_overridden": "Stay overridden"
      }
    }
  },
  "entity": {
    "button": {
      "day_now": {
        "name": "Day now"
      },
      "night_now": {
        "name": "Night now"
      }
    },
    "sensor": {
      "phase": {
        "name": "Phase",
        "state": {
          "day": "Day",
          "to_night": "Changing to night",
          "night": "Night",
          "to_day": "Changing to day"
        },
        "state_attributes": {
          "progress": {
            "name": "Progress"
          },
          "held": {
            "name": "Held"
          },
          "next_day_target": {
            "name": "Next day target"
          },
          "next_night_target": {
            "name": "Next night target"
          },
          "overridden_lights": {
            "name": "Overridden lights"
          }
        }
      }
    },
    "switch": {
      "automatic": {
        "name": "Automatic"
      }
    }
  }
}
```

Run: `cp custom_components/light_manager/strings.json custom_components/light_manager/translations/en.json`

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: `154 passed`.

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add custom_components/light_manager tests/test_entities.py
git commit -m "Add enable switches, Day now/Night now buttons and phase sensor"
```

---

### Task 8: CI, releases, HACS metadata and README

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `hacs.json`, `README.md`

**Interfaces:**
- Consumes:
  - `pyproject.toml` / `uv.lock` (`uv sync --locked`)
  - `custom_components/light_manager/manifest.json` (`version`, which the release workflow bumps)
- Produces:
  - **CI** runs on push to `main`, on pull requests and as a reusable workflow (`workflow_call`). It runs three jobs: test (ruff and pytest), hassfest and HACS validation.
  - **Release** is a manual `workflow_dispatch` with input `bump` (patch/minor/major). It runs CI, then:
    1. Bumps the manifest version.
    2. Commits `Release vX.Y.Z`, authored by whoever clicked Run, with no trailers.
    3. Creates an annotated tag and pushes the commit and tag atomically.
    4. Builds `light_manager.zip` from the integration folder.
    5. Publishes a GitHub release with generated notes.
  - `hacs.json`: `zip_release` with `filename: light_manager.zip`, so HACS installs from the release asset.

- [ ] **Step 1: Write the workflows**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
  workflow_call:

permissions:
  contents: read

jobs:
  test:
    name: Lint and test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.2.0
        with:
          enable-cache: true
      - name: Install
        run: uv sync --locked
      - name: Lint
        run: uv run ruff check .
      - name: Check formatting
        run: uv run ruff format --check .
      - name: Test
        run: uv run pytest -q

  hassfest:
    name: Hassfest
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: home-assistant/actions/hassfest@master

  hacs:
    name: HACS validation
    runs-on: ubuntu-latest
    steps:
      - uses: hacs/action@22.5.0
        with:
          category: integration
          ignore: brands
```

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  workflow_dispatch:
    inputs:
      bump:
        description: Which part of the version to bump
        type: choice
        options: [patch, minor, major]
        default: patch

concurrency:
  group: release
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  ci:
    if: github.ref == 'refs/heads/main'
    uses: ./.github/workflows/ci.yml

  release:
    name: Tag and publish
    needs: ci
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      MANIFEST: custom_components/light_manager/manifest.json
    steps:
      - uses: actions/checkout@v7

      - name: Bump version
        id: version
        env:
          BUMP: ${{ inputs.bump }}
        run: |
          IFS=. read -r major minor patch < <(jq -r .version "$MANIFEST")
          case "$BUMP" in
            major) major=$((major + 1)); minor=0; patch=0 ;;
            minor) minor=$((minor + 1)); patch=0 ;;
            patch) patch=$((patch + 1)) ;;
          esac
          version="$major.$minor.$patch"
          if git ls-remote --exit-code --tags origin "refs/tags/v$version" >/dev/null; then
            echo "::error::Tag v$version already exists"
            exit 1
          fi
          jq --arg v "$version" '.version = $v' "$MANIFEST" > manifest.tmp
          mv manifest.tmp "$MANIFEST"
          echo "version=$version" >> "$GITHUB_OUTPUT"

      - name: Commit and tag
        env:
          VERSION: ${{ steps.version.outputs.version }}
          ACTOR: ${{ github.actor }}
          ACTOR_ID: ${{ github.actor_id }}
        run: |
          git config user.name "$ACTOR"
          git config user.email "$ACTOR_ID+$ACTOR@users.noreply.github.com"
          git commit -am "Release v$VERSION"
          git tag -a "v$VERSION" -m "v$VERSION"
          git push --atomic origin HEAD:main "v$VERSION"

      - name: Build zip
        run: |
          cd custom_components/light_manager
          zip -r "$RUNNER_TEMP/light_manager.zip" . -x '__pycache__/*' '*.pyc'

      - name: Publish GitHub release
        env:
          GH_TOKEN: ${{ github.token }}
          VERSION: ${{ steps.version.outputs.version }}
        run: >
          gh release create "v$VERSION" "$RUNNER_TEMP/light_manager.zip"
          --title "v$VERSION" --generate-notes --verify-tag
```

- [ ] **Step 2: Lint the workflows**

Run: `docker run --rm -v "$PWD:/repo" --workdir /repo rhysd/actionlint:1.7.12 -verbose .github/workflows/ci.yml .github/workflows/release.yml`
Expected: `Found 0 errors in 2 files`. (The image bundles shellcheck, so the `run:` scripts are checked too.) If Docker isn't available, say so in your report and skip this step.

- [ ] **Step 3: HACS metadata and README**

Create `hacs.json`:

```json
{
  "name": "Light Manager",
  "homeassistant": "2026.9.0",
  "zip_release": true,
  "filename": "light_manager.zip"
}
```

Create `README.md`:

````markdown
# Light Manager

A Home Assistant integration that moves groups of lights between a **day** and a **night** brightness and color temperature, on a schedule you control.

- Each group has a day setting and a night setting (brightness %, color temperature K).
- Each change *ends* at its target time: sunrise/sunset shifted by ± minutes, or a fixed time of day.
- During the transition (30 minutes by default) the lights fade gradually.
- If you change a light by hand, only that light stops following the schedule. It returns to automatic when you turn it off and on again (configurable per group), or when the next transition starts.
- Lights without color temperature (for example Z-Wave dimmers) get brightness only.

## Install

1. In HACS, open **Custom repositories**, add `https://github.com/ajma/ha-light-manager` with the category **Integration**, then download **Light Manager**.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and add **Light Manager**. It asks no questions.
4. On the Light Manager entry, choose **Add light group**.

## Configure a group

**Step 1:** name, lights, day and night brightness and color temperature, the kind of day and night target (sunrise/sunset or a fixed time), transition length, and what happens when an overridden light is turned off.

**Step 2:** the sunrise/sunset offsets or the fixed times.

To change a group later, choose **Reconfigure** on it:
- **Edit group settings** reopens the two steps.
- **Customize a light** gives one light its own brightness or color temperature. Leave a field blank to follow the group.

Light groups made with the Group helper are expanded into their member lights. A light can belong to only one Light Manager group.

## Entities

| Entity | Global | Per group (e.g. "Living room") |
|---|---|---|
| Automatic switch | `switch.light_manager_automatic` | `switch.living_room_automatic` |
| Day now button | `button.light_manager_day_now` | `button.living_room_day_now` |
| Night now button | `button.light_manager_night_now` | `button.living_room_night_now` |
| Phase sensor | — | `sensor.living_room_phase` |

- **Automatic switches:** a group changes lights automatically only while both the global switch and its own switch are on. Turning automatic back on clears manual overrides and applies the current setting.
- **Day now / Night now:**
  - Applies that setting immediately and holds it until the next transition toward the other setting.
  - A group's buttons work even while it's not automatic.
  - The global buttons act on every group whose own switch is on.
- **Phase sensor:** `day`, `to_night`, `night` or `to_day`. Its attributes are `progress`, `held`, `next_day_target`, `next_night_target` and `overridden_lights`.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Releasing

Releases are made from GitHub Actions:

1. Go to **Actions → Release → Run workflow** on `main`.
2. Pick **patch**, **minor** or **major**.

The workflow:
1. Runs CI.
2. Bumps `version` in `manifest.json`.
3. Commits `Release vX.Y.Z` and tags it.
4. Publishes a GitHub release with `light_manager.zip`, which HACS installs.

HACS validation needs the GitHub repository to have a description and topics.
````

- [ ] **Step 4: Run hassfest locally**

Run:

```bash
rm -rf /tmp/hassfest && mkdir -p /tmp/hassfest && cp -r custom_components /tmp/hassfest/ \
  && find /tmp/hassfest -name __pycache__ -prune -exec rm -rf {} + \
  && docker run --rm -v /tmp/hassfest:/github/workspace ghcr.io/home-assistant/hassfest
```

Expected: ends with `Invalid integrations: 0`. If Docker isn't available, say so in your report and skip this step.

- [ ] **Step 5: Full check**

Run: `uv sync --locked && uv run ruff format --check . && uv run ruff check . && uv run pytest -q`
Expected: `154 passed`, lint clean.

- [ ] **Step 6: Commit**

```bash
git add .github hacs.json README.md
git commit -m "Add CI and release workflows, HACS metadata and README"
```

Notes:
- **Not part of this task:** creating the GitHub repository, pushing, and setting the repository description and topics, which HACS validation requires. Those are outward-facing actions for the user to approve.
- **The release workflow pushes to `main` with `GITHUB_TOKEN`.** A branch-protection rule on `main` would block that push.
