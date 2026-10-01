"""Setting up the config entry: a failed setup must not leave anything running."""

import datetime as dt

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.light_manager.const import DOMAIN, TICK_SECONDS
from custom_components.light_manager.group import GroupRuntime

from .common import ENTRY_ID, STORAGE_KEY, FakeLights, advance_to, group_data, local

NOON = local(2026, 9, 30, 12, 0)


async def test_failed_setup_stops_the_groups_it_started(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    lights: FakeLights,
    hass_storage: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freezer.move_to(NOON)
    lights.add_dimmer("light.first")
    lights.add_dimmer("light.second")
    started: list[GroupRuntime] = []
    original = GroupRuntime.async_start

    async def failing_start(self: GroupRuntime, stored) -> None:
        started.append(self)
        if self.subentry_id == "group_2":
            raise RuntimeError("group_2 could not start")
        await original(self, stored)

    monkeypatch.setattr(GroupRuntime, "async_start", failing_start)
    listeners = hass.bus.async_listeners().get(EVENT_CALL_SERVICE, 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={},
        subentries_data=[
            {
                "data": group_data(name=name, lights=[light]),
                "subentry_id": subentry_id,
                "subentry_type": "group",
                "title": name,
                "unique_id": None,
            }
            for subentry_id, name, light in (
                ("group_1", "First", "light.first"),
                ("group_2", "Second", "light.second"),
            )
        ],
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    first = started[0]
    assert first.subentry_id == "group_1"
    assert first._unsub_timer is None
    assert first._unsub_state is None
    assert hass.bus.async_listeners().get(EVENT_CALL_SERVICE, 0) == listeners
    assert STORAGE_KEY not in hass_storage  # half-started state must not be saved
    lights.clear()
    for count in range(1, 4):
        await advance_to(
            hass, freezer, NOON + count * dt.timedelta(seconds=TICK_SECONDS)
        )
    assert lights.calls == []
