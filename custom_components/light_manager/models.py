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
