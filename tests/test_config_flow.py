"""Config flow: parent entry, group subentries, reconfigure and customize (§5)."""

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.light_manager.const import DOMAIN

from .common import FakeLights, group_data
from .conftest import SetupIntegration

SETTINGS = {
    "name": "Bedroom",
    "lights": ["light.bed"],
    "day_brightness_pct": 90.0,  # selectors return floats
    "day_color_temp_kelvin": 3800.0,
    "day_target": "sun",
    "night_brightness_pct": 10.0,
    "night_color_temp_kelvin": 2000.0,
    "night_target": "fixed",
    "transition_min": 45.0,
    "off_behavior": "stay_overridden",
}


def suggested(result: FlowResult) -> dict[str, Any]:
    return {
        str(key): (key.description or {}).get("suggested_value")
        for key in result["data_schema"].schema
    }


async def start_add(hass: HomeAssistant, entry: ConfigEntry) -> FlowResult:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "group"), context={"source": SOURCE_USER}
    )


async def start_reconfigure(hass: HomeAssistant, entry: ConfigEntry) -> FlowResult:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "group"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "group_1"},
    )


async def configure(hass: HomeAssistant, result: FlowResult, data: dict) -> FlowResult:
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


@pytest.fixture
async def entry(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> ConfigEntry:
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    lights.add_color_temp("light.bed")
    return await setup_integration(group_data())


async def test_parent_entry_is_created_without_questions(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Light Manager"
    assert result["data"] == {}

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "single_instance_allowed"


async def test_add_group_with_defaults_suggested(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    result = await start_add(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert suggested(result) == {
        "name": None,
        "lights": None,
        "day_brightness_pct": 100,
        "day_color_temp_kelvin": 4000,
        "day_target": "sun",
        "night_brightness_pct": 20,
        "night_color_temp_kelvin": 2200,
        "night_target": "sun",
        "transition_min": 30,
        "off_behavior": "return_to_auto",
    }

    result = await configure(hass, result, SETTINGS)
    assert result["step_id"] == "timing"
    # Only the fields for the chosen target types (sunrise offset, night time).
    assert suggested(result) == {"day_offset_min": 0, "night_time": "21:00:00"}

    result = await configure(
        hass, result, {"day_offset_min": -15.0, "night_time": "22:30:00"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom"
    assert result["data"] == {
        "name": "Bedroom",
        "lights": ["light.bed"],
        "day": {"brightness_pct": 90, "color_temp_kelvin": 3800},
        "night": {"brightness_pct": 10, "color_temp_kelvin": 2000},
        "day_target": {"type": "sun", "offset_min": -15},
        "night_target": {"type": "fixed", "time": "22:30:00"},
        "transition_min": 45,
        "off_behavior": "stay_overridden",
        "light_overrides": {},
    }
    # Adding the subentry reloads the integration, which starts the new group.
    await hass.async_block_till_done()
    new_id = next(sid for sid in entry.subentries if sid != "group_1")
    assert set(entry.runtime_data.groups) == {"group_1", new_id}


async def add_helper(hass: HomeAssistant, members: list[str]) -> str:
    helper = er.async_get(hass).async_get_or_create(
        "light", "group", "downstairs", suggested_object_id="downstairs"
    )
    hass.states.async_set(helper.entity_id, "on", {"entity_id": members})
    return helper.entity_id


@pytest.mark.parametrize(
    ("changes", "field", "error"),
    [
        ({"name": "   "}, "name", "name_required"),
        ({"name": "living ROOM"}, "name", "name_taken"),
        ({"lights": []}, "lights", "no_lights"),
        ({"lights": ["light.bed", "light.dimmer"]}, "lights", "light_in_other_group"),
    ],
)
async def test_settings_validation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    changes: dict[str, Any],
    field: str,
    error: str,
) -> None:
    result = await start_add(hass, entry)

    result = await configure(hass, result, SETTINGS | changes)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {field: error}
    # The form keeps what the user typed.
    assert suggested(result)["night_brightness_pct"] == 10.0


async def test_light_in_another_group_through_a_helper(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    helper = await add_helper(hass, ["light.bed", "light.lamp"])
    result = await start_add(hass, entry)

    result = await configure(hass, result, SETTINGS | {"lights": [helper]})

    assert result["errors"] == {"lights": "light_in_other_group"}
    assert result["description_placeholders"]["conflicts"] == "light.lamp"


@pytest.mark.parametrize(
    ("day_time", "night_time", "transition", "ok"),
    [
        ("07:00:00", "07:20:00", 30, False),
        ("21:00:00", "21:00:00", 0, False),
        ("23:50:00", "00:10:00", 30, False),  # gap across midnight
        ("07:00:00", "07:30:00", 30, True),
    ],
)
async def test_fixed_targets_must_leave_room_for_the_transition(
    hass: HomeAssistant,
    entry: ConfigEntry,
    day_time: str,
    night_time: str,
    transition: int,
    ok: bool,
) -> None:
    result = await start_add(hass, entry)
    result = await configure(
        hass,
        result,
        SETTINGS | {"day_target": "fixed", "transition_min": float(transition)},
    )

    result = await configure(
        hass, result, {"day_time": day_time, "night_time": night_time}
    )

    if ok:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["step_id"] == "timing"
        assert result["errors"] == {"base": "transition_too_long"}


async def test_reconfigure_menu_edits_settings_and_drops_stale_overrides(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> None:
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    overrides = {
        "light.lamp": {"day_brightness_pct": 80},
        "light.dimmer": {"night_brightness_pct": 5},
    }
    entry = await setup_integration(group_data(light_overrides=overrides))

    result = await start_reconfigure(hass, entry)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["settings", "customize"]

    result = await configure(hass, result, {"next_step_id": "settings"})
    assert result["step_id"] == "settings"
    assert suggested(result)["name"] == "Living room"
    assert suggested(result)["night_target"] == "fixed"

    form = suggested(result) | {
        "name": "Living room",  # unchanged name is not "taken"
        "lights": ["light.dimmer"],
        "night_target": "sun",
    }
    result = await configure(hass, result, form)
    assert suggested(result) == {"day_time": "07:00:00", "night_offset_min": 0}

    result = await configure(
        hass, result, {"day_time": "06:45:00", "night_offset_min": 20.0}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    data = entry.subentries["group_1"].data
    assert data["lights"] == ["light.dimmer"]
    assert data["day_target"] == {"type": "fixed", "time": "06:45:00"}
    assert data["night_target"] == {"type": "sun", "offset_min": 20}
    assert data["light_overrides"] == {"light.dimmer": {"night_brightness_pct": 5}}


async def test_rename_updates_the_subentry_title(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    result = await start_reconfigure(hass, entry)
    result = await configure(hass, result, {"next_step_id": "settings"})
    result = await configure(hass, result, suggested(result) | {"name": "Den"})
    result = await configure(hass, result, suggested(result))

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["group_1"].title == "Den"


async def test_customize_a_light(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> None:
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    overrides = {"light.lamp": {"day_brightness_pct": 80}}
    entry = await setup_integration(group_data(light_overrides=overrides))

    result = await start_reconfigure(hass, entry)
    result = await configure(hass, result, {"next_step_id": "customize"})
    assert result["step_id"] == "customize"
    selector = result["data_schema"].schema["light"]
    assert selector.config["options"] == [
        {"value": "light.lamp", "label": "lamp (customized)"},
        {"value": "light.dimmer", "label": "dimmer"},
    ]

    result = await configure(hass, result, {"light": "light.dimmer"})
    assert result["step_id"] == "customize_light"
    # Brightness only: the dimmer has no color temperature.
    assert suggested(result) == {
        "day_brightness_pct": None,
        "night_brightness_pct": None,
    }
    assert result["description_placeholders"] == {
        "light": "dimmer",
        "day": "100%, 4000 K",
        "night": "20%, 2200 K",
    }

    result = await configure(hass, result, {"night_brightness_pct": 5.0})

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["group_1"].data["light_overrides"] == {
        "light.lamp": {"day_brightness_pct": 80},
        "light.dimmer": {"night_brightness_pct": 5},
    }


async def test_clearing_every_field_removes_the_customization(
    hass: HomeAssistant, lights: FakeLights, setup_integration: SetupIntegration
) -> None:
    lights.add_color_temp("light.lamp")
    overrides = {
        "light.lamp": {"day_brightness_pct": 80, "night_color_temp_kelvin": 1800}
    }
    entry = await setup_integration(
        group_data(lights=["light.lamp"], light_overrides=overrides)
    )
    result = await start_reconfigure(hass, entry)
    result = await configure(hass, result, {"next_step_id": "customize"})
    result = await configure(hass, result, {"light": "light.lamp"})
    assert suggested(result) == {
        "day_brightness_pct": 80,
        "day_color_temp_kelvin": None,
        "night_brightness_pct": None,
        "night_color_temp_kelvin": 1800,
    }

    result = await configure(hass, result, {})

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["group_1"].data["light_overrides"] == {}
