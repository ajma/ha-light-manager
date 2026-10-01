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
