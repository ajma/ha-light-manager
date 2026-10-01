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
