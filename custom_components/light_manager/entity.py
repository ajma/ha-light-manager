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
