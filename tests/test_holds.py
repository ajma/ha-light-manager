"""Day now / Night now holds and the global controls (spec §6.5, §8)."""

from homeassistant.core import HomeAssistant

from custom_components.light_manager.light_tracker import Mode
from custom_components.light_manager.models import Phase

from .common import FakeLights, advance_to, group_data, local
from .conftest import SetupIntegration

NOON = local(2026, 9, 30, 12, 0)
NIGHT_LAMP = {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
DAY_LAMP = {"brightness": 255, "color_temp_kelvin": 4000, "transition": 2}


async def start(
    freezer, lights: FakeLights, setup_integration: SetupIntegration, when=NOON
):
    freezer.move_to(when)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    entry = await setup_integration(group_data())
    lights.clear()
    return entry, entry.runtime_data.groups["group_1"]


async def test_night_now_holds_until_the_morning_ramp(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(freezer, lights, setup_integration)

    await group.async_press(Phase.NIGHT)

    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    state = group.phase_state()
    assert state.phase is Phase.NIGHT
    assert state.held is True
    assert group.hold.expiry == local(2026, 10, 1, 6, 30)

    # An override made during the hold survives the suppressed evening ramp.
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()
    lights.clear()
    for moment in (local(2026, 9, 30, 20, 30), local(2026, 9, 30, 20, 45)):
        await advance_to(hass, freezer, moment)
    assert lights.calls == []
    assert group.trackers["light.lamp"].mode is Mode.OVERRIDDEN

    # The hold ends when the to_day ramp starts; that ramp clears overrides.
    await advance_to(hass, freezer, local(2026, 10, 1, 6, 30))
    assert group.hold is None
    assert group.trackers["light.lamp"].mode is Mode.AUTO
    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    assert group.phase_state().phase is Phase.TO_DAY


async def test_day_now_mid_ramp_cancels_the_ramp(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(
        freezer, lights, setup_integration, local(2026, 9, 30, 20, 40)
    )

    await group.async_press(Phase.DAY)
    assert lights.calls_for("light.lamp") == [DAY_LAMP]
    lights.clear()

    for moment in (local(2026, 9, 30, 20, 40, 30), local(2026, 9, 30, 21, 0)):
        await advance_to(hass, freezer, moment)

    assert lights.calls == []
    assert group.phase_state().phase is Phase.DAY
    assert group.hold.expiry == local(2026, 10, 1, 20, 30)


async def test_press_resends_a_target_equal_to_the_last_command(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=30)  # user override
    await hass.async_block_till_done()

    # The last command sent to the lamp was the day setpoint; it must be resent.
    await group.async_press(Phase.DAY)

    assert lights.calls_for("light.lamp") == [DAY_LAMP]
    assert group.trackers["light.lamp"].mode is Mode.AUTO


async def test_group_button_works_while_the_group_is_disabled(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    _, group = await start(freezer, lights, setup_integration)
    await group.async_set_enabled(False)

    await group.async_press(Phase.NIGHT)
    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    lights.clear()

    lights.set("light.lamp", "off")
    lights.set("light.lamp", "on", brightness=200)  # no turn-on handling
    await advance_to(hass, freezer, local(2026, 10, 1, 6, 45))  # no ramp
    assert lights.calls == []


async def test_global_press_skips_groups_whose_switch_is_off(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    lights.add_dimmer("light.porch")
    entry = await setup_integration(
        group_data(),
        group_data(name="Porch", lights=["light.porch"]),
    )
    manager = entry.runtime_data
    await manager.groups["group_2"].async_set_enabled(False)
    await manager.async_set_global_enabled(False)  # global switch doesn't matter
    lights.clear()

    await manager.async_press_all(Phase.NIGHT)

    assert lights.calls_for("light.lamp") == [NIGHT_LAMP]
    assert lights.calls_for("light.porch") == []


async def test_global_switch_stops_and_reactivates_groups(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry, group = await start(freezer, lights, setup_integration)
    manager = entry.runtime_data

    await manager.async_set_global_enabled(False)
    assert group.active is False
    lights.update("light.lamp", brightness=30)
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))
    assert lights.calls == []

    await manager.async_set_global_enabled(True)

    assert group.active is True
    assert lights.calls_for("light.lamp") == [
        {"brightness": 153, "color_temp_kelvin": 2839, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == [{"brightness": 153, "transition": 2}]


async def test_group_switch_on_with_global_off_stays_inactive(
    hass: HomeAssistant, freezer, lights, setup_integration
) -> None:
    entry, group = await start(freezer, lights, setup_integration)
    await entry.runtime_data.async_set_global_enabled(False)
    await group.async_set_enabled(False)

    await group.async_set_enabled(True)

    assert group.active is False
    assert lights.calls == []
