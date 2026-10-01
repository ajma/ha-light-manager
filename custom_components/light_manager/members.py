"""Group membership: expand HA Group-helper lights into their members (spec §10)."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def expand_lights(
    hass: HomeAssistant, entity_ids: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Return (member lights, group helpers), order-preserving, without duplicates.

    A light whose registry entry has platform "group" is a helper: its state's
    entity_id attribute lists its members, expanded recursively. A helper with no
    state yet has no members. Anything else (including lights not loaded yet) is
    a member light.
    """
    registry = er.async_get(hass)
    lights: list[str] = []
    helpers: list[str] = []

    def visit(entity_id: str, path: frozenset[str]) -> None:
        if entity_id in path:
            return
        entry = registry.async_get(entity_id)
        if entry is not None and entry.platform == "group":
            if entity_id not in helpers:
                helpers.append(entity_id)
            state = hass.states.get(entity_id)
            members = state.attributes.get(ATTR_ENTITY_ID, []) if state else []
            for member in members:
                visit(member, path | {entity_id})
        elif entity_id not in lights:
            lights.append(entity_id)

    for entity_id in entity_ids:
        visit(entity_id, frozenset())
    return lights, helpers
