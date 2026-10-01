"""Runtime tests: ramps, overrides, turn-on handling and failures (fake clock)."""

import asyncio
import datetime as dt
import logging
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.light_manager.const import STEP_FADE_SECONDS, TICK_SECONDS
from custom_components.light_manager.curve import LightCommand
from custom_components.light_manager.light_tracker import Mode
from custom_components.light_manager.models import Phase

from .common import FakeLights, advance_to, group_data, local
from .conftest import SetupIntegration

NOON = local(2026, 9, 30, 12, 0)
DAY_CMD = {"brightness": 255, "color_temp_kelvin": 4000, "transition": 2}


def runtime(entry, subentry_id: str = "group_1"):
    return entry.runtime_data.groups[subentry_id]


async def start(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    lights: FakeLights,
    setup_integration: SetupIntegration,
    when: dt.datetime = NOON,
    **changes,
):
    """Lamp (color temp) and dimmer on at full; integration set up at `when`."""
    freezer.move_to(when)
    lights.add_color_temp("light.lamp")
    lights.add_dimmer("light.dimmer")
    entry = await setup_integration(group_data(**changes))
    return entry


async def test_startup_sends_current_target_to_lights_that_are_on(
    hass, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    lights.add_color_temp("light.lamp", brightness=100, kelvin=3000)
    lights.add_dimmer("light.dimmer", state="off")

    await setup_integration(group_data())

    assert lights.calls_for("light.lamp") == [DAY_CMD]
    assert lights.calls_for("light.dimmer") == []


async def test_full_ramp_commands_every_tick_and_lands_on_target(
    hass, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration, local(2026, 9, 30, 20, 0))
    lights.clear()

    moment = local(2026, 9, 30, 20, 30)
    while moment <= local(2026, 9, 30, 21, 0):
        await advance_to(hass, freezer, moment)
        moment += dt.timedelta(seconds=30)

    lamp = lights.calls_for("light.lamp")
    dimmer = lights.calls_for("light.dimmer")
    assert len(lamp) == 61
    assert len(dimmer) == 61
    assert lamp[0] == DAY_CMD
    assert lamp[20] == {"brightness": 187, "color_temp_kelvin": 3143, "transition": 2}
    assert lamp[40] == {"brightness": 119, "color_temp_kelvin": 2588, "transition": 2}
    assert lamp[-1] == {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    assert dimmer[-1] == {"brightness": 51, "transition": 2}

    lights.clear()
    await advance_to(hass, freezer, local(2026, 9, 30, 23, 0))
    assert lights.calls == []


async def test_manual_change_overrides_only_that_light(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(
        hass, freezer, lights, setup_integration, local(2026, 9, 30, 20, 40)
    )

    # The user dims the lamp after our command's settle window has passed.
    freezer.tick(dt.timedelta(seconds=15))
    lights.update("light.lamp", brightness=30)
    await hass.async_block_till_done()
    lights.clear()
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 41))

    assert lights.calls_for("light.lamp") == []
    assert len(lights.calls_for("light.dimmer")) == 1
    assert runtime(entry).phase_state().overridden_lights == ["light.lamp"]


async def test_late_and_mid_fade_reports_are_not_overrides(
    hass, freezer, lights, setup_integration
) -> None:
    # A Z-Wave dimmer at full that only reports on its own schedule.
    freezer.move_to(local(2026, 9, 30, 22, 0))
    lights.add_dimmer("light.dimmer", brightness=255)
    lights.silent.add("light.dimmer")
    entry = await setup_integration(group_data(lights=["light.dimmer"]))
    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]

    lights.update("light.dimmer", brightness=150)  # mid-fade, fresh context
    freezer.tick(dt.timedelta(seconds=25))
    lights.update("light.dimmer", brightness=51)  # late final report
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_ramp_start_clears_overrides(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=80)
    await hass.async_block_till_done()
    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    lights.clear()

    await advance_to(hass, freezer, local(2026, 9, 30, 20, 30))

    assert runtime(entry).trackers["light.lamp"].mode is Mode.AUTO
    assert lights.calls_for("light.lamp") == [DAY_CMD]


async def test_overridden_light_off_and_on_returns_to_auto(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=80)
    lights.set("light.lamp", "off")
    lights.set("light.lamp", "on", brightness=80, color_temp_kelvin=3000)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.AUTO
    assert lights.calls_for("light.lamp")[-1] == {
        "brightness": 255,
        "color_temp_kelvin": 4000,
        "transition": 0,
    }


async def test_stay_overridden_survives_off_and_on(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(
        hass, freezer, lights, setup_integration, off_behavior="stay_overridden"
    )
    lights.update("light.lamp", brightness=80)
    lights.set("light.lamp", "off")
    lights.clear()
    lights.set("light.lamp", "on", brightness=80)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []


async def test_plain_turn_on_gets_target_with_no_fade(
    hass, freezer, lights, setup_integration
) -> None:
    await start(hass, freezer, lights, setup_integration, local(2026, 9, 30, 22, 0))
    lights.set("light.dimmer", "off")
    lights.clear()

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.dimmer"}, blocking=True
    )
    await hass.async_block_till_done()

    assert lights.calls_for("light.dimmer") == [{}, {"brightness": 51, "transition": 0}]


async def test_explicit_turn_on_marks_light_overridden(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.set("light.lamp", "off")
    lights.clear()

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.lamp", "brightness_pct": 40},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == [{"brightness_pct": 40}]


async def test_unavailable_round_trip_keeps_mode(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.update("light.lamp", brightness=80)  # override the lamp
    lights.clear()

    for entity_id in ("light.lamp", "light.dimmer"):
        lights.set(entity_id, "unavailable")
        lights.set(entity_id, "on", brightness=100)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.lamp"].mode is Mode.OVERRIDDEN
    assert lights.calls_for("light.lamp") == []
    assert lights.calls_for("light.dimmer") == [{"brightness": 255, "transition": 0}]


async def test_light_missing_at_startup_gets_target_when_it_appears(
    hass, freezer, lights, setup_integration, caplog
) -> None:
    freezer.move_to(local(2026, 9, 30, 22, 0))
    lights.add_color_temp("light.lamp")
    with caplog.at_level(logging.WARNING):
        entry = await setup_integration(group_data())
    assert "light.dimmer doesn't exist" in caplog.text

    lights.add_dimmer("light.dimmer", brightness=255)  # Z-Wave finished loading
    await hass.async_block_till_done()

    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 0}]
    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_failed_command_does_not_block_others_and_is_retried(
    hass, freezer, lights, setup_integration, caplog
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.fail.add("light.lamp")
    lights.clear()

    with caplog.at_level(logging.WARNING):
        await runtime(entry).async_press(Phase.NIGHT)
    assert "light.lamp: command failed" in caplog.text
    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]
    lamp = runtime(entry).trackers["light.lamp"]
    assert lamp.expected == LightCommand(51, 2200)  # kept, to be resent
    assert lamp.unconfirmed

    # The next evaluation (20:30, inside the hold so nothing is reset) retries.
    lights.fail.clear()
    lights.clear()
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 30))
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == []


async def test_failed_command_in_a_plateau_is_retried_on_the_next_tick(
    hass, freezer, lights, setup_integration, caplog
) -> None:
    # Noon is far from any ramp: without a retry wake the next evaluation would
    # be the suppressed 20:30 ramp, hours away.
    entry = await start(hass, freezer, lights, setup_integration)
    lights.fail.add("light.lamp")
    lights.clear()

    with caplog.at_level(logging.WARNING):
        await runtime(entry).async_press(Phase.NIGHT)
    assert "light.lamp: command failed" in caplog.text
    assert lights.calls_for("light.dimmer") == [{"brightness": 51, "transition": 2}]

    lights.fail.clear()
    lights.clear()
    tick = dt.timedelta(seconds=TICK_SECONDS)
    await advance_to(hass, freezer, NOON + tick)
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == []

    # It succeeded, so the retry is over: no further commands.
    lights.clear()
    await advance_to(hass, freezer, NOON + 2 * tick)
    assert lights.calls == []


async def test_late_report_of_a_failed_command_is_not_an_override(
    hass, freezer, lights, setup_integration
) -> None:
    # Z-Wave JS raises when a call times out, yet the dimmer often applies the
    # value and reports it later, without our context (spec §10).
    entry = await start(hass, freezer, lights, setup_integration)
    lights.fail.add("light.lamp")
    lights.clear()
    await runtime(entry).async_press(Phase.NIGHT)
    lights.fail.clear()
    lights.clear()

    freezer.tick(dt.timedelta(seconds=8))
    lights.update("light.lamp", brightness=51, color_temp_kelvin=2200)  # new Context
    await hass.async_block_till_done()

    lamp = runtime(entry).trackers["light.lamp"]
    assert lamp.mode is Mode.AUTO

    # The retry still goes out on the next tick, since the call never confirmed.
    tick = dt.timedelta(seconds=TICK_SECONDS)
    await advance_to(hass, freezer, NOON + tick)
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]
    assert not lamp.unconfirmed
    assert lamp.mode is Mode.AUTO

    lights.clear()
    await advance_to(hass, freezer, NOON + 2 * tick)
    assert lights.calls == []


async def test_failure_streak_warns_once_and_logs_the_recovery(
    hass, freezer, lights, setup_integration, caplog
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    lights.fail.add("light.lamp")
    caplog.set_level(logging.DEBUG, logger="custom_components.light_manager")
    tick = dt.timedelta(seconds=TICK_SECONDS)

    await runtime(entry).async_press(Phase.NIGHT)
    await advance_to(hass, freezer, NOON + tick)  # the retry fails too

    ours = [r for r in caplog.records if r.name.startswith("custom_components")]
    warnings = [r.getMessage() for r in ours if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "light.lamp: command failed" in warnings[0]
    assert any(
        r.levelno == logging.DEBUG and "light.lamp: command failed" in r.getMessage()
        for r in ours
    )
    assert "recovered" not in caplog.text

    lights.fail.clear()
    await advance_to(hass, freezer, NOON + 2 * tick)

    ours = [r for r in caplog.records if r.name.startswith("custom_components")]
    recovered = [r for r in ours if "recovered" in r.getMessage()]
    assert len(recovered) == 1
    assert recovered[0].levelno == logging.INFO
    assert "light.lamp" in recovered[0].getMessage()
    assert len([r for r in ours if r.levelno == logging.WARNING]) == 1


# --- Late delivery after a manual off (spec §7.4) ---

RAMP_TICK = local(2026, 9, 30, 20, 40, 30)


async def held_tick_then_manual_off(hass, freezer, lights, setup_integration):
    """A ramp tick sends to the dimmer, which is held in flight; the user turns it off.

    Returns (entry, finish): `finish` releases the held command, which then lands,
    and waits for everything to settle.
    """
    freezer.move_to(local(2026, 9, 30, 20, 40))
    lights.add_dimmer("light.dimmer")
    entry = await setup_integration(group_data(lights=["light.dimmer"]))
    arrived, release = lights.hold_next_turn_on()
    lights.clear()

    freezer.move_to(RAMP_TICK)
    async_fire_time_changed(hass)  # the tick's command is held, so don't block on it
    await arrived.wait()
    freezer.tick(dt.timedelta(seconds=1))
    lights.set("light.dimmer", "off")  # the wall switch

    async def finish() -> None:
        release.set()
        await hass.async_block_till_done()

    return entry, finish


async def test_command_landing_after_a_manual_off_is_reversed(
    hass, freezer, lights, setup_integration
) -> None:
    entry, finish = await held_tick_then_manual_off(
        hass, freezer, lights, setup_integration
    )

    await finish()  # the queued command lands and turns the light back on

    assert lights.calls_for("light.dimmer", "turn_off") == [{}]
    assert hass.states.get("light.dimmer").state == "off"
    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_dashboard_turn_on_after_a_manual_off_is_not_reversed(
    hass, freezer, lights, setup_integration
) -> None:
    entry, finish = await held_tick_then_manual_off(
        hass, freezer, lights, setup_integration
    )

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.dimmer"}, blocking=True
    )
    for _ in range(100):  # the tick is still held, so block_till_done would hang
        if len(lights.calls_for("light.dimmer")) == 3:
            break
        await asyncio.sleep(0)

    assert lights.calls_for("light.dimmer", "turn_off") == []
    transitions = [c.get("transition") for c in lights.calls_for("light.dimmer")]
    assert transitions == [2, None, 0]  # the held tick, the dashboard, our target
    assert hass.states.get("light.dimmer").state == "on"

    await finish()  # the old command lands later; nothing reverses anything

    assert lights.calls_for("light.dimmer", "turn_off") == []
    assert hass.states.get("light.dimmer").state == "on"
    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_explicit_turn_on_after_a_manual_off_is_not_reversed(
    hass, freezer, lights, setup_integration
) -> None:
    entry, finish = await held_tick_then_manual_off(
        hass, freezer, lights, setup_integration
    )

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.dimmer", "brightness": 80},
        blocking=True,
    )
    await finish()

    assert lights.calls_for("light.dimmer", "turn_off") == []
    assert hass.states.get("light.dimmer").state == "on"
    assert runtime(entry).trackers["light.dimmer"].mode is Mode.OVERRIDDEN


async def test_wall_off_and_on_after_the_light_reported_is_not_reversed(
    hass, freezer, lights, setup_integration
) -> None:
    # Once the dimmer has reported our command (without our context, as Z-Wave
    # does) the command can't land late, so a quick wall off/on is the user's.
    freezer.move_to(local(2026, 9, 30, 20, 40))
    lights.add_dimmer("light.dimmer")
    lights.silent.add("light.dimmer")  # accepts the call, reports on its own
    await setup_integration(group_data(lights=["light.dimmer"]))
    level = lights.calls_for("light.dimmer")[-1]["brightness"]
    lights.update("light.dimmer", brightness=level)  # the device's report

    lights.set("light.dimmer", "off")  # the wall switch, off and on again
    lights.clear()
    lights.set("light.dimmer", "on", brightness=level)
    await hass.async_block_till_done()

    assert lights.calls_for("light.dimmer", "turn_off") == []
    assert lights.calls_for("light.dimmer") == [{"brightness": level, "transition": 0}]
    assert hass.states.get("light.dimmer").state == "on"


async def test_overlapping_applies_send_the_command_once(
    hass, freezer, lights, setup_integration
) -> None:
    # Two applies racing (a timer tick and a button press, say) must not both pass
    # should_send before either has recorded its command.
    entry = await start(hass, freezer, lights, setup_integration)
    group = runtime(entry)
    group.trackers["light.lamp"].reset_auto()
    lights.clear()

    await asyncio.gather(group._async_apply(2), group._async_apply(2))

    assert lights.calls_for("light.lamp") == [DAY_CMD]


async def test_send_failing_after_stop_does_not_rearm_the_timer(
    hass, freezer, lights, setup_integration
) -> None:
    # Reload-on-change unloads the entry while commands may be in flight; a stale
    # runtime must not keep commanding lights next to its replacement.
    entry = await start(hass, freezer, lights, setup_integration)
    group = runtime(entry)
    release = asyncio.Event()

    async def hung_turn_on(call: ServiceCall) -> None:
        lights.calls.append(call)
        await release.wait()
        raise HomeAssistantError("did not respond")

    hass.services.async_register("light", "turn_on", hung_turn_on)
    lights.clear()

    press = hass.async_create_task(group.async_press(Phase.NIGHT))
    for _ in range(100):  # let both sends reach the hung service
        if len(lights.calls) == 2:
            break
        await asyncio.sleep(0)
    assert len(lights.calls) == 2

    group.async_stop()  # the entry unloads with both sends in flight
    release.set()
    await press
    lights.clear()

    tick = dt.timedelta(seconds=TICK_SECONDS)
    for count in range(1, 6):
        await advance_to(hass, freezer, NOON + count * tick)
    assert lights.calls == []


async def test_nothing_runs_after_stop(
    hass, freezer, lights, setup_integration
) -> None:
    # A reload replaces the runtime; the old one's late evaluations and delayed
    # saves must not command lights or overwrite the new runtime's stored state.
    entry = await start(hass, freezer, lights, setup_integration)
    manager = entry.runtime_data
    group = runtime(entry)
    await manager.async_stop()
    group.trackers["light.lamp"].reset_auto()  # a send would be due
    lights.clear()

    await group._async_evaluate(NOON + dt.timedelta(seconds=TICK_SECONDS))
    await group._async_apply(STEP_FADE_SECONDS)
    with patch.object(manager._store, "async_delay_save") as delay_save:
        manager.async_schedule_save()

    assert lights.calls == []
    assert group._unsub_timer is None
    delay_save.assert_not_called()


async def test_light_override_values_are_used(
    hass, freezer, lights, setup_integration
) -> None:
    await start(
        hass,
        freezer,
        lights,
        setup_integration,
        local(2026, 9, 30, 22, 0),
        light_overrides={"light.dimmer": {"night_brightness_pct": 5}},
    )

    assert lights.calls_for("light.dimmer") == [{"brightness": 13, "transition": 2}]
    assert lights.calls_for("light.lamp") == [
        {"brightness": 51, "color_temp_kelvin": 2200, "transition": 2}
    ]


async def test_brightness_none_report_while_on_is_not_an_override(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    lights.update("light.dimmer", brightness=None)
    lights.update("light.dimmer", brightness=255)
    await hass.async_block_till_done()

    assert runtime(entry).trackers["light.dimmer"].mode is Mode.AUTO


async def test_group_helper_is_expanded_into_members(
    hass, freezer, lights, setup_integration
) -> None:
    freezer.move_to(NOON)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "light", "group", "living", suggested_object_id="living_group"
    )
    lights.add_color_temp("light.lamp", brightness=100)
    lights.add_dimmer("light.dimmer", brightness=100)
    lights.add_dimmer("light.extra", brightness=100)
    hass.states.async_set(
        "light.living_group", "on", {"entity_id": ["light.lamp", "light.dimmer"]}
    )

    entry = await setup_integration(group_data(lights=["light.living_group"]))
    assert list(runtime(entry).trackers) == ["light.lamp", "light.dimmer"]
    assert lights.calls_for("light.living_group") == []
    lights.clear()

    hass.states.async_set(
        "light.living_group",
        "on",
        {"entity_id": ["light.lamp", "light.dimmer", "light.extra"]},
    )
    await hass.async_block_till_done()

    assert "light.extra" in runtime(entry).trackers
    assert lights.calls_for("light.extra") == [{"brightness": 255, "transition": 2}]
    assert lights.calls_for("light.lamp") == []


async def test_inactive_group_makes_no_automatic_changes(
    hass, freezer, lights, setup_integration
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)
    group = runtime(entry)
    await group.async_set_enabled(False)
    lights.clear()

    lights.update("light.lamp", brightness=80)  # not classified while inactive
    lights.set("light.dimmer", "off")
    lights.set("light.dimmer", "on", brightness=10)  # no turn-on handling
    await advance_to(hass, freezer, local(2026, 9, 30, 20, 45))  # no ramp

    assert lights.calls == []
    assert group.trackers["light.lamp"].mode is Mode.AUTO

    await group.async_set_enabled(True)

    assert lights.calls_for("light.lamp") == [
        {"brightness": 153, "color_temp_kelvin": 2839, "transition": 2}
    ]
    assert lights.calls_for("light.dimmer") == [{"brightness": 153, "transition": 2}]


@pytest.mark.parametrize("enabled", [True, False])
async def test_group_switch_state_is_saved(
    hass, freezer, lights, setup_integration, hass_storage, enabled
) -> None:
    entry = await start(hass, freezer, lights, setup_integration)

    await runtime(entry).async_set_enabled(enabled)
    await hass.config_entries.async_unload(entry.entry_id)

    stored = hass_storage["light_manager.lm_entry"]["data"]
    assert stored["groups"]["group_1"]["enabled"] is enabled
