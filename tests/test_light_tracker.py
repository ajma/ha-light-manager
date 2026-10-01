"""Tests for light_tracker.py: Z-Wave timing scenarios and mode changes."""

import datetime as dt

import pytest

from custom_components.light_manager.curve import LightCapabilities, LightCommand
from custom_components.light_manager.light_tracker import (
    LightTracker,
    Mode,
    Reading,
    is_explicit_turn_on,
)

T0 = dt.datetime(2026, 9, 30, 20, 40, tzinfo=dt.UTC)
DIMMER = LightCapabilities(brightness=True, color_temp=False, emulated_color_temp=False)
CT = LightCapabilities(
    brightness=True,
    color_temp=True,
    emulated_color_temp=False,
    min_kelvin=2000,
    max_kelvin=6500,
)
COLOR_ONLY = LightCapabilities(
    brightness=True, color_temp=False, emulated_color_temp=True
)


def at(seconds: float) -> dt.datetime:
    return T0 + dt.timedelta(seconds=seconds)


def dim(brightness: int | None) -> Reading:
    return Reading(brightness, None, "brightness" if brightness else None)


def ct(brightness: int, kelvin: int | None, mode: str = "color_temp") -> Reading:
    return Reading(brightness, kelvin, mode)


def sent_dimmer(
    pre: int, target: int, fade: float = 2, finished: float | None = 0
) -> LightTracker:
    """A dimmer we commanded from `pre` to `target` at T0 with context c1.

    The call returned `finished` seconds after T0; None leaves it in flight.
    """
    tracker = LightTracker("light.dimmer")
    command = LightCommand(target)
    tracker.begin_command(command, "c1", T0, fade, dim(pre))
    if finished is not None:
        tracker.command_finished(command, at(finished))
    return tracker


# --- Z-Wave scenarios (spec §11) ---


def test_late_report_with_fresh_context_matching_target_is_ours() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    result = tracker.classify(dim(120), dim(51), "zwave-poll", at(30), DIMMER)

    assert not result.manual
    assert "rule 2" in result.reason


def test_mid_fade_reports_are_ours() -> None:
    tracker = sent_dimmer(pre=255, target=51)

    first = tracker.classify(dim(255), dim(180), "zwave-1", at(1), DIMMER)
    second = tracker.classify(dim(180), dim(90), "zwave-2", at(2.5), DIMMER)

    assert not first.manual
    assert not second.manual
    assert "rule 3" in second.reason


def test_dimmer_settling_above_requested_minimum_is_ours() -> None:
    # Asked for 5% (13/255); the dimmer stops at 10% (26/255) within the window.
    tracker = sent_dimmer(pre=51, target=13)

    result = tracker.classify(dim(51), dim(26), "zwave-1", at(8), DIMMER)

    assert not result.manual
    assert "rule 3" in result.reason


def test_user_sets_100_percent_is_manual() -> None:
    tracker = sent_dimmer(pre=120, target=115)

    result = tracker.classify(dim(115), dim(255), "user", at(5), DIMMER)

    assert result.manual
    assert result.reason == "brightness 255/255"


def test_nudge_within_tolerance_is_ours_even_later() -> None:
    tracker = sent_dimmer(pre=60, target=51)

    result = tracker.classify(dim(51), dim(56), "user", at(600), DIMMER)

    assert not result.manual


def test_nudge_within_settle_band_only_counts_inside_the_window() -> None:
    tracker = sent_dimmer(pre=70, target=51)

    inside = tracker.classify(dim(51), dim(65), "zwave", at(11.9), DIMMER)
    outside = tracker.classify(dim(51), dim(65), "zwave", at(12.1), DIMMER)

    assert not inside.manual
    assert outside.manual


def test_settle_window_runs_from_when_the_call_returned() -> None:
    # A busy Z-Wave queue: the call returned 10 s after it began (spec §7.2).
    tracker = sent_dimmer(pre=255, target=51, finished=10)

    # 15 s after sent_at (window would have closed at 12 s), 5 s after finished_at.
    result = tracker.classify(dim(255), dim(150), "zwave", at(15), DIMMER)
    late = tracker.classify(dim(150), dim(120), "zwave", at(22.1), DIMMER)

    assert not result.manual
    assert "rule 3" in result.reason
    assert late.manual


def test_report_while_the_call_is_in_flight_is_settling_however_late() -> None:
    tracker = sent_dimmer(pre=255, target=51, finished=None)

    result = tracker.classify(dim(255), dim(150), "zwave", at(60), DIMMER)

    assert not result.manual
    assert "rule 3" in result.reason


def test_our_context_explains_anything() -> None:
    tracker = sent_dimmer(pre=255, target=51)

    result = tracker.classify(dim(255), dim(200), "c1", at(300), DIMMER)

    assert result == (False, "rule 1: our context")


def test_change_with_nothing_sent_is_manual() -> None:
    tracker = LightTracker("light.dimmer")

    assert tracker.classify(dim(100), dim(150), "user", at(0), DIMMER).manual


def test_brightness_none_while_on_is_not_a_change() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    assert not tracker.classify(dim(51), dim(None), "zwave", at(60), DIMMER).manual
    assert not tracker.classify(dim(None), dim(51), "zwave", at(61), DIMMER).manual


def test_unchanged_values_are_not_a_change() -> None:
    tracker = LightTracker("light.dimmer")

    result = tracker.classify(dim(100), dim(100), "user", at(0), DIMMER)

    assert result == (False, "no tracked change")


# --- Color temperature ---


def sent_ct(pre: Reading, command: LightCommand) -> LightTracker:
    tracker = LightTracker("light.lamp")
    tracker.begin_command(command, "c1", T0, 2, pre)
    tracker.command_finished(command, T0)
    return tracker


def test_color_temp_within_mired_tolerance_is_ours() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    # 2600 K is ~1.8 mireds from 2588 K.
    result = tracker.classify(ct(187, 3143), ct(119, 2600), "zwave", at(60), CT)

    assert not result.manual


def test_user_color_temp_change_is_manual() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    result = tracker.classify(ct(119, 2588), ct(119, 4000), "user", at(60), CT)

    assert result == (True, "color_temp 4000 K")


def test_switch_to_color_mode_is_manual_even_during_settle() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    result = tracker.classify(
        ct(119, 2588), ct(119, None, mode="hs"), "user", at(1), CT
    )

    assert result.manual
    assert result.reason == "color mode -> hs"


def test_color_mode_change_with_our_context_is_ours() -> None:
    tracker = sent_ct(ct(187, 3143), LightCommand(119, 2588))

    result = tracker.classify(ct(119, 2588), ct(119, None, mode="hs"), "c1", at(1), CT)

    assert not result.manual


def test_emulated_color_temp_light_only_watches_brightness() -> None:
    tracker = LightTracker("light.strip")
    tracker.begin_command(LightCommand(51, 2200), "c1", T0, 2, ct(51, 2200, "hs"))

    result = tracker.classify(
        ct(51, 2200, "hs"), ct(51, 6000, "hs"), "user", at(60), COLOR_ONLY
    )

    assert not result.manual


# --- Sending and modes ---


def test_should_send_only_when_auto_and_different() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    assert not tracker.should_send(LightCommand(51))
    assert tracker.should_send(LightCommand(52))
    tracker.mark_overridden(at(5))
    assert not tracker.should_send(LightCommand(52))
    assert tracker.mode is Mode.OVERRIDDEN
    assert tracker.overridden_at == at(5)


def test_reset_auto_forces_resend_of_same_target() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    tracker.mark_overridden(at(5))

    tracker.reset_auto()

    assert tracker.mode is Mode.AUTO
    assert tracker.overridden_at is None
    assert tracker.should_send(LightCommand(51))


def test_failed_command_stays_expected_and_unconfirmed() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    command = LightCommand(40)

    tracker.begin_command(command, "c2", at(30), 2, dim(51))
    assert tracker.finished_at is None  # in flight
    tracker.command_failed(command, at(40))

    assert tracker.expected == command
    assert tracker.unconfirmed
    assert tracker.finished_at == at(40)
    assert tracker.should_send(command)  # resent even though it equals expected


def test_failed_command_does_not_undo_a_newer_command() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    first, second = LightCommand(40), LightCommand(30)

    tracker.begin_command(first, "c2", at(30), 2, dim(51))
    tracker.begin_command(second, "c3", at(31), 2, dim(51))
    tracker.command_failed(first, at(35))  # the older send fails after the newer began

    assert tracker.expected == second
    assert not tracker.unconfirmed
    assert tracker.finished_at is None  # the newer call is still in flight
    assert not tracker.should_send(second)


def test_failed_command_does_not_undo_a_reset_while_in_flight() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    in_flight = LightCommand(40)

    tracker.begin_command(in_flight, "c2", at(30), 2, dim(51))
    tracker.reset_auto()
    tracker.command_failed(in_flight, at(40))

    assert tracker.expected is None
    assert not tracker.unconfirmed
    assert tracker.should_send(LightCommand(51))


def test_late_report_of_a_failed_command_is_still_ours() -> None:
    # Z-Wave timed out our call, then the dimmer applied it and reported 8 s later.
    tracker = sent_dimmer(pre=255, target=51, finished=None)
    tracker.command_failed(tracker.expected, at(5))

    result = tracker.classify(dim(255), dim(51), "zwave", at(13), DIMMER)

    assert not result.manual
    assert "rule 2" in result.reason


def test_overlapping_sends_only_the_last_failure_counts() -> None:
    tracker = LightTracker("light.dimmer")
    a, b = LightCommand(80), LightCommand(70)
    tracker.begin_command(a, "ca", T0, 2, dim(255))
    tracker.begin_command(b, "cb", at(1), 2, dim(255))

    tracker.command_failed(a, at(5))  # superseded: ignored
    assert tracker.expected == b
    assert not tracker.unconfirmed
    tracker.command_failed(b, at(6))

    assert tracker.expected == b
    assert tracker.unconfirmed
    assert tracker.should_send(b)


def test_command_finished_only_counts_for_the_last_command() -> None:
    tracker = LightTracker("light.dimmer")
    a, b = LightCommand(80), LightCommand(70)
    tracker.begin_command(a, "ca", T0, 2, dim(255))
    tracker.begin_command(b, "cb", at(1), 2, dim(255))

    tracker.command_finished(a, at(3))
    assert tracker.finished_at is None
    tracker.command_finished(b, at(4))

    assert tracker.finished_at == at(4)
    assert not tracker.unconfirmed
    assert not tracker.should_send(b)


def test_beginning_a_command_clears_unconfirmed_and_finished() -> None:
    tracker = sent_dimmer(pre=255, target=51)
    tracker.command_failed(tracker.expected, at(5))

    tracker.begin_command(LightCommand(51), "c2", at(30), 2, dim(51))

    assert not tracker.unconfirmed
    assert tracker.finished_at is None
    assert not tracker.should_send(LightCommand(51))


def test_unconfirmed_only_forces_a_resend_while_auto() -> None:
    tracker = sent_dimmer(pre=255, target=51)
    tracker.command_failed(tracker.expected, at(5))
    tracker.mark_overridden(at(6))

    assert not tracker.should_send(LightCommand(51))


@pytest.mark.parametrize("clear", ["reset_auto", "turned_off", "unavailable"])
def test_unconfirmed_is_cleared_with_expected(clear) -> None:
    tracker = sent_dimmer(pre=255, target=51)
    tracker.command_failed(tracker.expected, at(5))

    if clear == "reset_auto":
        tracker.reset_auto()
    elif clear == "turned_off":
        tracker.on_turned_off("return_to_auto", at(6))
    else:
        tracker.on_unavailable()

    assert tracker.expected is None
    assert not tracker.unconfirmed


def test_own_contexts_are_remembered_up_to_five() -> None:
    tracker = LightTracker("light.dimmer")
    for i in range(6):
        tracker.begin_command(LightCommand(i + 1), f"c{i}", at(i), 2, dim(1))

    assert not tracker.is_own_context("c0")
    assert all(tracker.is_own_context(f"c{i}") for i in range(1, 6))
    assert not tracker.is_own_context(None)


@pytest.mark.parametrize(
    ("behavior", "mode_after", "changed"),
    [
        ("return_to_auto", Mode.AUTO, True),
        ("stay_overridden", Mode.OVERRIDDEN, False),
    ],
)
def test_turned_off_with_each_off_behavior(behavior, mode_after, changed) -> None:
    tracker = sent_dimmer(pre=120, target=51)
    tracker.mark_overridden(at(5))

    assert tracker.on_turned_off(behavior, at(6)) is changed
    assert tracker.mode is mode_after
    assert tracker.expected is None


def test_turned_off_while_auto_reports_no_mode_change() -> None:
    tracker = sent_dimmer(pre=120, target=51)

    assert tracker.on_turned_off("return_to_auto", at(6)) is False
    assert tracker.expected is None


def test_unavailable_round_trip_keeps_mode_and_forces_resend() -> None:
    tracker = sent_dimmer(pre=120, target=51)
    tracker.mark_overridden(at(5))

    tracker.on_unavailable()

    assert tracker.mode is Mode.OVERRIDDEN
    assert tracker.expected is None


# --- Late delivery after a manual off (spec §7.4) ---


def switched_off(
    finished: float | None = 1, off_after: float = 3, fade: float = 2
) -> LightTracker:
    """Commanded at T0, then turned off `off_after` seconds later (window: +12 s)."""
    tracker = sent_dimmer(pre=255, target=51, fade=fade, finished=finished)
    tracker.on_turned_off("return_to_auto", at(off_after))
    return tracker


def test_turning_off_records_when() -> None:
    tracker = sent_dimmer(pre=255, target=51)

    tracker.on_turned_off("stay_overridden", at(7))

    assert tracker.off_at == at(7)


def test_late_delivery_with_our_context() -> None:
    tracker = switched_off()

    assert tracker.late_delivery("c1", at(60))  # no window for our own context


def test_late_delivery_while_the_call_is_in_flight() -> None:
    tracker = switched_off(finished=None)

    assert tracker.late_delivery("wall", at(60))


def test_late_delivery_within_the_window_after_the_call_returned() -> None:
    # finished_at 1 s + fade 2 s + settle 10 s = 13 s.
    assert switched_off().late_delivery("wall", at(13))


def test_not_late_delivery_after_the_window() -> None:
    assert not switched_off().late_delivery("wall", at(13.1))


def test_not_late_delivery_when_the_light_went_off_before_the_send() -> None:
    tracker = switched_off(off_after=-5)

    assert not tracker.late_delivery("c1", at(1))


def test_not_late_delivery_without_a_recorded_off_or_send() -> None:
    assert not sent_dimmer(pre=255, target=51).late_delivery("c1", at(5))
    assert not LightTracker("light.dimmer").late_delivery("c1", at(5))


def test_late_delivery_consumes_the_off_on_every_turn_on() -> None:
    tracker = switched_off()

    assert not tracker.late_delivery("wall", at(60))  # too late: False, off consumed
    assert tracker.off_at is None
    assert not tracker.late_delivery("c1", at(61))  # the stale off can't fire later


def test_late_delivery_fires_at_most_once_per_command() -> None:
    tracker = switched_off()

    assert tracker.late_delivery("c1", at(5))
    tracker.on_turned_off("return_to_auto", at(6))  # off and on again, no new send

    assert not tracker.late_delivery("c1", at(7))


# --- Explicit turn-on detection (spec §7.4) ---


@pytest.mark.parametrize(
    ("service", "data", "explicit"),
    [
        ("turn_on", {"entity_id": "light.lamp", "brightness_pct": 40}, True),
        ("turn_on", {"color_temp_kelvin": 2700}, True),
        ("toggle", {"color_name": "red"}, True),
        ("turn_on", {"profile": "relax"}, True),
        ("turn_on", {"brightness_step_pct": -10}, True),
        ("turn_on", {"entity_id": "light.lamp"}, False),
        ("turn_on", {"transition": 3}, False),
        ("turn_off", {"brightness": 10}, False),
    ],
)
def test_is_explicit_turn_on(service, data, explicit) -> None:
    assert is_explicit_turn_on(service, data) is explicit


def test_reading_from_attributes() -> None:
    attrs = {"brightness": 51, "color_temp_kelvin": 2200, "color_mode": "color_temp"}

    assert Reading.from_attributes(attrs) == Reading(51, 2200, "color_temp")
    assert Reading.from_attributes({}) == Reading(None, None, None)
