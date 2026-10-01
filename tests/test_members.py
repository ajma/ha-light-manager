"""Tests for members.py (Group-helper expansion, spec §10)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.light_manager.members import expand_lights

from .common import add_config_entry_helper


def add_helper(hass: HomeAssistant, object_id: str, members: list[str] | None) -> str:
    entry = er.async_get(hass).async_get_or_create(
        "light", "group", object_id, suggested_object_id=object_id
    )
    if members is not None:
        hass.states.async_set(entry.entity_id, "on", {"entity_id": members})
    return entry.entity_id


async def test_plain_lights_pass_through_in_order_without_duplicates(
    hass: HomeAssistant,
) -> None:
    lights, helpers = expand_lights(hass, ["light.b", "light.a", "light.b"])

    assert lights == ["light.b", "light.a"]
    assert helpers == []


async def test_helpers_expand_recursively(hass: HomeAssistant) -> None:
    upstairs = add_helper(hass, "upstairs", ["light.bed", "light.hall"])
    house = add_helper(hass, "house", [upstairs, "light.kitchen", "light.hall"])

    lights, helpers = expand_lights(hass, [house, "light.porch"])

    assert lights == ["light.bed", "light.hall", "light.kitchen", "light.porch"]
    assert helpers == [house, upstairs]


async def test_helper_without_state_has_no_members_yet(hass: HomeAssistant) -> None:
    helper = add_helper(hass, "later", None)

    assert expand_lights(hass, [helper]) == ([], [helper])


async def test_non_group_light_with_entity_id_attribute_is_a_light(
    hass: HomeAssistant,
) -> None:
    # A Hue room or Zigbee2MQTT group: not an HA Group helper, so one light.
    hass.states.async_set("light.hue_room", "on", {"entity_id": ["light.x"]})

    assert expand_lights(hass, ["light.hue_room"]) == (["light.hue_room"], [])


async def test_helper_cycles_terminate(hass: HomeAssistant) -> None:
    first = er.async_get(hass).async_get_or_create(
        "light", "group", "first", suggested_object_id="first"
    )
    second = add_helper(hass, "second", [first.entity_id, "light.lamp"])
    hass.states.async_set(first.entity_id, "on", {"entity_id": [second]})

    lights, helpers = expand_lights(hass, [first.entity_id])

    assert lights == ["light.lamp"]
    assert helpers == [first.entity_id, second]


async def test_helper_members_come_from_its_config_entry_while_unavailable(
    hass: HomeAssistant,
) -> None:
    helper = add_config_entry_helper(hass, "zwave", ["light.bed", "light.hall"])
    assert "entity_id" not in hass.states.get(helper).attributes

    assert expand_lights(hass, [helper, "light.porch"]) == (
        ["light.bed", "light.hall", "light.porch"],
        [helper],
    )


async def test_config_entry_members_can_be_registry_ids(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    bed = registry.async_get_or_create("light", "zwave_js", "bed-1")
    helper = add_config_entry_helper(hass, "zwave", [bed.id, "light.hall", "gone-id"])

    # Entity IDs and registry UUIDs both resolve; an unknown UUID is skipped.
    assert expand_lights(hass, [helper]) == ([bed.entity_id, "light.hall"], [helper])


async def test_config_entry_helpers_expand_recursively(hass: HomeAssistant) -> None:
    upstairs = add_config_entry_helper(hass, "upstairs", ["light.bed"])
    house = add_config_entry_helper(hass, "house", [upstairs, "light.kitchen"])

    assert expand_lights(hass, [house]) == (
        ["light.bed", "light.kitchen"],
        [house, upstairs],
    )


async def test_config_entry_without_members_falls_back_to_the_state(
    hass: HomeAssistant,
) -> None:
    # Not a group-domain entry (or no "entities" option): read the state instead.
    other = MockConfigEntry(domain="other", options={"entities": ["light.nope"]})
    other.add_to_hass(hass)
    entry = er.async_get(hass).async_get_or_create(
        "light", "group", "odd", config_entry=other, suggested_object_id="odd"
    )
    hass.states.async_set(entry.entity_id, "on", {"entity_id": ["light.lamp"]})

    assert expand_lights(hass, [entry.entity_id]) == (["light.lamp"], [entry.entity_id])
