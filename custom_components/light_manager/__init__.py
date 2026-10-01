"""Light Manager: day/night brightness and color temperature for light groups."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import Manager

type LightManagerConfigEntry = ConfigEntry[Manager]

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(
    hass: HomeAssistant, entry: LightManagerConfigEntry
) -> bool:
    """Start the manager for the parent entry and all group subentries."""
    manager = Manager(hass, entry)
    try:
        await manager.async_start()
        entry.runtime_data = manager
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # Don't leak the timers and listeners of groups that already started, and
        # don't save: a half-started manager would overwrite the good stored state.
        await manager.async_stop(save=False)
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: LightManagerConfigEntry) -> None:
    """Spec §10: any entry or subentry change reloads everything."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: LightManagerConfigEntry
) -> bool:
    """Stop timers and listeners and save state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
