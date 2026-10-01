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
