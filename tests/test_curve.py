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
