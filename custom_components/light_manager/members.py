"""Group membership: expand HA Group-helper lights into their members (spec §10)."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITIES
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

GROUP_DOMAIN = "group"


def expand_lights(
    hass: HomeAssistant, entity_ids: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Return (member lights, group helpers), order-preserving, without duplicates.

    A light whose registry entry has platform "group" is a helper, expanded
    recursively. Its members come from its config entry (`options["entities"]`,
    entity IDs or registry IDs), because HA drops the entity_id state attribute
    while a helper is unavailable, as a group of Z-Wave lights is at startup. A
    YAML helper has no config entry, so its entity_id attribute is read instead;
    with no state yet it has no members. Anything else (including lights not
    loaded yet) is a member light.
    """
    registry = er.async_get(hass)
    lights: list[str] = []
    helpers: list[str] = []

    def members_of(entry: er.RegistryEntry) -> list[str]:
        if config_entry_id := entry.config_entry_id:
            config_entry = hass.config_entries.async_get_entry(config_entry_id)
            if (
                config_entry is not None
                and config_entry.domain == GROUP_DOMAIN
                and CONF_ENTITIES in config_entry.options
            ):
                return [
                    resolved
                    for member in config_entry.options[CONF_ENTITIES]
                    if (resolved := er.async_resolve_entity_id(registry, member))
                ]
        state = hass.states.get(entry.entity_id)
        return list(state.attributes.get(ATTR_ENTITY_ID, [])) if state else []

    def visit(entity_id: str, path: frozenset[str]) -> None:
        if entity_id in path:
            return
        entry = registry.async_get(entity_id)
        if entry is not None and entry.platform == GROUP_DOMAIN:
            if entity_id not in helpers:
                helpers.append(entity_id)
            for member in members_of(entry):
                visit(member, path | {entity_id})
        elif entity_id not in lights:
            lights.append(entity_id)

    for entity_id in entity_ids:
        visit(entity_id, frozenset())
    return lights, helpers
