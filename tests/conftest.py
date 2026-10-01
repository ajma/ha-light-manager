"""Shared fixtures."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.light_manager.const import DOMAIN

from .common import ENTRY_ID, STORAGE_KEY, FakeLights

type SetupIntegration = Callable[..., Awaitable[MockConfigEntry]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load custom_components/ in every test that uses hass."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")


@pytest.fixture
def lights(hass: HomeAssistant) -> FakeLights:
    return FakeLights(hass)


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> AsyncGenerator[SetupIntegration]:
    """Factory: set up the parent entry with group subentries (and stored state).

    Groups get subentry IDs group_1, group_2, ... in order. The entry is
    unloaded at teardown so timers and listeners are cleaned up.
    """
    entries: list[MockConfigEntry] = []

    async def _setup(
        *groups: dict[str, Any], stored: dict[str, Any] | None = None
    ) -> MockConfigEntry:
        if stored is not None:
            hass_storage[STORAGE_KEY] = {
                "version": 1,
                "minor_version": 1,
                "key": STORAGE_KEY,
                "data": stored,
            }
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id=ENTRY_ID,
            title="Light Manager",
            data={},
            subentries_data=[
                {
                    "data": data,
                    "subentry_id": f"group_{index}",
                    "subentry_type": "group",
                    "title": data["name"],
                    "unique_id": None,
                }
                for index, data in enumerate(groups, start=1)
            ],
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entries.append(entry)
        return entry

    yield _setup
    for entry in entries:
        if entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
