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
