"""Entities: IDs, devices, switch/button semantics and the phase sensor (§8)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.light_manager.const import DOMAIN

from .common import ENTRY_ID, FakeLights, advance_to, group_data, local
from .conftest import SetupIntegration

NOON = local(2026, 9, 30, 12, 0)
GROUP_ENTITIES = {
    "switch.living_room_automatic": "group_1_automatic",
    "button.living_room_day_now": "group_1_day_now",
    "button.living_room_night_now": "group_1_night_now",
    "sensor.living_room_phase": "group_1_phase",
}
GLOBAL_ENTITIES = {
    "switch.light_manager_automatic": f"{ENTRY_ID}_automatic",
    "button.light_manager_day_now": f"{ENTRY_ID}_day_now",
    "button.light_manager_night_now": f"{ENTRY_ID}_night_now",
}


async def start(
    hass: HomeAssistant,
    freezer,
    lights: FakeLights,
    setup_integration: SetupIntegration,
    *groups: dict,
):
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    lights.add_dimmer("light.porch")
    entry = await setup_integration(*(groups or (group_data(),)))
    lights.clear()
    return entry


async def call(hass: HomeAssistant, domain: str, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_entity_ids_unique_ids_and_devices(
    hass: HomeAssistant, freezer, lights, setup_integration, caplog
) -> None:
    await start(hass, freezer, lights, setup_integration)
    # HA's frame helper reports deprecated usage, e.g. shadowing Entity.group.
    assert "Detected that" not in caplog.text
    entities = er.async_get(hass)
    devices = dr.async_get(hass)

    for entity_id, unique_id in (GLOBAL_ENTITIES | GROUP_ENTITIES).items():
        entity = entities.async_get(entity_id)
        assert entity is not None, entity_id
        assert entity.unique_id == unique_id
    assert entities.async_get("sensor.light_manager_phase") is None

    group_device = devices.async_get_device_by_identifier((DOMAIN, "group_1"), ENTRY_ID)
    assert group_device.name == "Living room"
    assert group_device.config_entries_subentries == {ENTRY_ID: {"group_1"}}
    global_device = devices.async_get_device_by_identifier((DOMAIN, ENTRY_ID), ENTRY_ID)
    assert global_device.name == "Light Manager"
    assert global_device.config_entries_subentries == {ENTRY_ID: {None}}
    for entity_id in GROUP_ENTITIES:
        assert entities.async_get(entity_id).config_subentry_id == "group_1"


async def test_renaming_a_group_keeps_entity_ids(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries["group_1"],
        title="Den",
        data=group_data(name="Den"),
    )
    await hass.async_block_till_done()

    for entity_id in GROUP_ENTITIES:
        assert hass.states.get(entity_id) is not None, entity_id
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "group_1"), ENTRY_ID
    )
    assert device.name == "Den"


async def test_group_switch(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    group = entry.runtime_data.groups["group_1"]
    assert hass.states.get("switch.living_room_automatic").state == "on"

    await call(hass, "switch", "turn_off", "switch.living_room_automatic")

    assert hass.states.get("switch.living_room_automatic").state == "off"
    assert group.enabled is False
    assert group.active is False

    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))
    assert lights.calls == []
    # The sensor keeps showing the schedule while the group is inactive.
    assert hass.states.get("sensor.living_room_phase").state == "to_night"

    await call(hass, "switch", "turn_on", "switch.living_room_automatic")
    assert lights.calls_for("light.dimmer") == [{"brightness": 153, "transition": 2}]


async def test_global_switch(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    await call(hass, "switch", "turn_off", "switch.light_manager_automatic")

    assert hass.states.get("switch.light_manager_automatic").state == "off"
    # The group's own switch is unchanged, but the group is inactive.
    assert hass.states.get("switch.living_room_automatic").state == "on"
    assert entry.runtime_data.groups["group_1"].active is False

    await call(hass, "switch", "turn_on", "switch.light_manager_automatic")
    assert entry.runtime_data.groups["group_1"].active is True


async def test_group_button_and_sensor_attributes(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration)
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.state == "day"
    assert sensor.attributes["options"] == ["day", "to_night", "night", "to_day"]
    assert sensor.attributes["progress"] is None
    assert sensor.attributes["held"] is False
    assert sensor.attributes["next_day_target"] == "2026-10-01T14:00:00+00:00"
    assert sensor.attributes["next_night_target"] == "2026-10-01T04:00:00+00:00"
    assert sensor.attributes["overridden_lights"] == []

    await call(hass, "button", "press", "button.living_room_night_now")

    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.state == "night"
    assert sensor.attributes["held"] is True


async def test_sensor_follows_the_ramp_and_overrides(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration)

    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.state == "to_night"
    assert sensor.attributes["progress"] == 50

    freezer.tick(15)
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.living_room_phase")
    assert sensor.attributes["overridden_lights"] == ["light.lamp"]


async def test_global_button_acts_on_groups_whose_switch_is_on(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    await start(
        hass,
        freezer,
        lights,
        setup_integration,
        group_data(),
        group_data(name="Porch", lights=["light.porch"]),
    )
    await call(hass, "switch", "turn_off", "switch.porch_automatic")
    await call(hass, "switch", "turn_off", "switch.light_manager_automatic")

    await call(hass, "button", "press", "button.light_manager_night_now")

    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]
    assert lights.calls_for("light.porch") == []
    assert hass.states.get("sensor.living_room_phase").attributes["held"] is True
    assert hass.states.get("sensor.porch_phase").attributes["held"] is False


async def test_switch_states_survive_a_reload(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    await call(hass, "switch", "turn_off", "switch.living_room_automatic")
    await call(hass, "switch", "turn_off", "switch.light_manager_automatic")

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("switch.living_room_automatic").state == "off"
    assert hass.states.get("switch.light_manager_automatic").state == "off"
