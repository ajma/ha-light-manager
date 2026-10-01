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
