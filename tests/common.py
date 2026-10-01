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
