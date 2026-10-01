"""Restore after restart/reload (spec §9)."""

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.light_manager.light_tracker import Mode
from custom_components.light_manager.models import Phase

from .common import STORAGE_KEY, add_config_entry_helper, group_data, local

NOON = local(2026, 9, 30, 12, 0)


def stored(**group: Any) -> dict[str, Any]:
    return {
        "global_enabled": True,
        "groups": {
            "group_1": {"enabled": True, "hold": None, "overridden": {}, **group}
        },
    }


def iso(*args: int) -> str:
    return local(*args).isoformat()


async def test_active_hold_is_restored(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 13, 0))
    lights.add_color_temp("light.lamp")
    hold = {"phase": "night", "pressed_at": iso(2026, 9, 30, 12, 0)}

    entry = await setup_integration(group_data(), stored=stored(hold=hold))

    group = entry.runtime_data.groups["group_1"]
    assert group.phase_state().held is True
    assert group.phase_state().phase is Phase.NIGHT
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]


async def test_expired_hold_is_dropped(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    hold = {"phase": "night", "pressed_at": iso(2026, 9, 29, 12, 0)}

    entry = await setup_integration(group_data(), stored=stored(hold=hold))

    group = entry.runtime_data.groups["group_1"]
    assert group.hold is None
    assert group.phase_state().phase is Phase.DAY


async def test_override_kept_when_no_ramp_started_since(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 14, 0))
    lights.add_color_temp("light.lamp", brightness=30)
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN
    assert tracker.overridden_at == local(2026, 9, 30, 13, 0)
    assert lights.calls_for("light.lamp") == []


async def test_override_dropped_after_a_ramp_started(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp", brightness=30)
    data = stored(overridden={"light.lamp": iso(2026, 9, 29, 19, 0)})

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.AUTO
    assert len(lights.calls_for("light.lamp")) == 1


async def test_override_survives_a_ramp_suppressed_by_the_hold(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 21, 30))
    lights.add_color_temp("light.lamp", brightness=30)
    data = stored(
        hold={"phase": "night", "pressed_at": iso(2026, 9, 30, 12, 0)},
        overridden={"light.lamp": iso(2026, 9, 30, 15, 0)},
    )

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN


async def test_return_to_auto_override_dropped_for_light_known_off(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 14, 0))
    lights.add_color_temp("light.lamp", state="off")
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(), stored=data)

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.AUTO


async def test_override_kept_for_off_light_with_stay_overridden(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(local(2026, 9, 30, 14, 0))
    lights.add_color_temp("light.lamp", state="off")
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(
        group_data(off_behavior="stay_overridden"), stored=data
    )

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN


async def test_override_kept_while_light_has_not_loaded_yet(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    # Z-Wave can finish loading after us: unknown state is not "known off".
    freezer.move_to(local(2026, 9, 30, 14, 0))
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(), stored=data)
    lights.add_color_temp("light.lamp", brightness=30)
    await hass.async_block_till_done()

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []


async def test_override_restored_for_member_of_an_unavailable_group_helper(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    # At startup a group of Z-Wave lights is unavailable and has no entity_id
    # attribute, but its config entry still lists the members (spec §10).
    freezer.move_to(local(2026, 9, 30, 14, 0))
    helper = add_config_entry_helper(hass, "living", ["light.lamp"])
    data = stored(overridden={"light.lamp": iso(2026, 9, 30, 13, 0)})

    entry = await setup_integration(group_data(lights=[helper]), stored=data)
    lights.add_color_temp("light.lamp", brightness=30)  # Z-Wave finished loading
    await hass.async_block_till_done()

    tracker = entry.runtime_data.groups["group_1"].trackers["light.lamp"]
    assert tracker.mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []


async def test_switch_states_are_restored(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    data = stored(enabled=False)
    data["global_enabled"] = False

    entry = await setup_integration(group_data(), stored=data)

    assert entry.runtime_data.global_enabled is False
    assert entry.runtime_data.groups["group_1"].enabled is False
    assert lights.calls == []


async def test_state_saved_on_unload_and_unknown_groups_dropped(
    hass: HomeAssistant, freezer, lights, setup_integration, hass_storage
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    data = stored()
    data["groups"]["deleted_group"] = {"enabled": False, "hold": None, "overridden": {}}
    entry = await setup_integration(group_data(), stored=data)
    group = entry.runtime_data.groups["group_1"]
    await group.async_press(Phase.NIGHT)
    freezer.tick(60)
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(entry.entry_id)

    saved = hass_storage[STORAGE_KEY]["data"]
    assert set(saved["groups"]) == {"group_1"}
    assert saved["groups"]["group_1"] == {
        "enabled": True,
        "hold": {"phase": "night", "pressed_at": "2026-09-30T19:00:00+00:00"},
        "overridden": {"light.lamp": "2026-09-30T19:01:00+00:00"},
    }
