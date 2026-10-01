"""Tests for schedule.py (pure; fake sun, US/Pacific)."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from custom_components.light_manager.models import Phase, TargetTime
from custom_components.light_manager.schedule import Schedule, fixed_targets_valid

PACIFIC = ZoneInfo("US/Pacific")
MIN30 = dt.timedelta(minutes=30)


def local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=PACIFIC)


def sept30(h: int, mi: int = 0, s: int = 0) -> dt.datetime:
    return local(2026, 9, 30, h, mi, s)


def fixed(hour: int, minute: int = 0) -> TargetTime:
    return TargetTime("fixed", time=dt.time(hour, minute))


def sun_target(offset_min: int = 0) -> TargetTime:
    return TargetTime("sun", offset=dt.timedelta(minutes=offset_min))


def fake_sun(missing=frozenset()):
    """Sunrise 06:50, sunset 18:40 local every day, except (date, event) in missing."""

    def sun(day: dt.date, event: str) -> dt.datetime | None:
        if (day, event) in missing:
            return None
        clock = dt.time(6, 50) if event == "sunrise" else dt.time(18, 40)
        return dt.datetime.combine(day, clock, PACIFIC).astimezone(dt.UTC)

    return sun


def no_sun(day: dt.date, event: str) -> None:
    return None


def fixed_schedule(transition: dt.timedelta = MIN30) -> Schedule:
    return Schedule(fixed(7), fixed(21), transition, fake_sun(), PACIFIC)


@pytest.mark.parametrize(
    ("now", "phase", "progress"),
    [
        (sept30(6, 0), Phase.NIGHT, None),
        (sept30(6, 30), Phase.TO_DAY, 0.0),
        (sept30(6, 45), Phase.TO_DAY, 0.5),
        (sept30(7, 0), Phase.DAY, None),
        (sept30(12, 0), Phase.DAY, None),
        (sept30(20, 30), Phase.TO_NIGHT, 0.0),
        (sept30(20, 40), Phase.TO_NIGHT, 1 / 3),
        (sept30(20, 59, 59), Phase.TO_NIGHT, 1799 / 1800),
        (sept30(21, 0), Phase.NIGHT, None),
        (sept30(23, 59), Phase.NIGHT, None),
    ],
)
def test_fixed_target_phases(now, phase, progress) -> None:
    info = fixed_schedule().phase_at(now)

    assert info.phase == phase
    if progress is None:
        assert info.progress is None
    else:
        assert info.progress == pytest.approx(progress)


def test_next_targets_reported() -> None:
    info = fixed_schedule().phase_at(sept30(12, 0))

    assert info.next_day_target == local(2026, 10, 1, 7, 0)
    assert info.next_night_target == sept30(21, 0)
    assert info.target == sept30(21, 0)
    assert info.window_start == sept30(20, 30)


def test_sun_targets_with_offsets() -> None:
    schedule = Schedule(sun_target(-15), sun_target(20), MIN30, fake_sun(), PACIFIC)

    assert schedule.phase_at(sept30(6, 4)).phase == Phase.NIGHT
    morning = schedule.phase_at(sept30(6, 20))
    assert morning.phase == Phase.TO_DAY
    assert morning.progress == pytest.approx(0.5)
    assert schedule.phase_at(sept30(6, 35)).phase == Phase.DAY
    evening = schedule.phase_at(sept30(18, 45))
    assert evening.phase == Phase.TO_NIGHT
    assert evening.progress == pytest.approx(0.5)
    assert schedule.phase_at(sept30(19, 0)).phase == Phase.NIGHT


def test_close_targets_shorten_the_ramp() -> None:
    # Night target 20 min after the day target: the to_night ramp can't start
    # before the day target, so it lasts 20 min instead of 30.
    schedule = Schedule(fixed(7), fixed(7, 20), MIN30, fake_sun(), PACIFIC)

    info = schedule.phase_at(sept30(7, 10))
    assert info.phase == Phase.TO_NIGHT
    assert info.window_start == sept30(7, 0)
    assert info.progress == pytest.approx(0.5)
    morning = schedule.phase_at(sept30(6, 45))
    assert morning.phase == Phase.TO_DAY
    assert morning.progress == pytest.approx(0.5)


def test_one_missing_sunset_keeps_day() -> None:
    sun = fake_sun(missing={(dt.date(2026, 9, 30), "sunset")})
    schedule = Schedule(sun_target(), sun_target(), MIN30, sun, PACIFIC)

    # No sunset on 9/30: day continues through the night and next morning
    # (no ramp back toward a day setpoint we're already at).
    assert schedule.phase_at(sept30(20, 0)).phase == Phase.DAY
    assert schedule.phase_at(local(2026, 10, 1, 6, 40)).phase == Phase.DAY
    evening = schedule.phase_at(local(2026, 10, 1, 18, 20))
    assert evening.phase == Phase.TO_NIGHT
    assert evening.progress == pytest.approx(1 / 3)


def test_sun_events_missing_for_forty_days() -> None:
    missing = {
        (dt.date(2026, 10, 1) + dt.timedelta(days=i), event)
        for i in range(40)
        for event in ("sunrise", "sunset")
    }
    schedule = Schedule(sun_target(), sun_target(), MIN30, fake_sun(missing), PACIFIC)

    info = schedule.phase_at(local(2026, 10, 1, 12, 0))

    assert info.phase == Phase.NIGHT
    assert info.next_day_target == local(2026, 11, 10, 6, 50)
    assert info.next_night_target == local(2026, 11, 10, 18, 40)


def test_no_sun_events_at_all() -> None:
    schedule = Schedule(sun_target(), sun_target(), MIN30, no_sun, PACIFIC)

    info = schedule.phase_at(sept30(12, 0))

    assert info.phase == Phase.DAY
    assert info.progress is None
    assert info.target is None
    assert schedule.hold_expiry(Phase.NIGHT, sept30(12, 0)) is None
    assert schedule.ramp_starts_between(sept30(0, 0), sept30(23, 0)) == []


def test_transition_zero_switches_instantly() -> None:
    schedule = fixed_schedule(dt.timedelta(0))

    assert schedule.phase_at(sept30(20, 59, 59)).phase == Phase.DAY
    assert schedule.phase_at(sept30(21, 0)).phase == Phase.NIGHT
    assert schedule.phase_at(sept30(6, 59, 59)).phase == Phase.NIGHT
    assert schedule.phase_at(sept30(7, 0)).phase == Phase.DAY


@pytest.mark.parametrize(
    ("held", "pressed_at", "expiry"),
    [
        (Phase.NIGHT, sept30(12, 0), local(2026, 10, 1, 6, 30)),
        (Phase.DAY, sept30(23, 0), local(2026, 10, 1, 20, 30)),
        # Pressed inside the ramp it opposes: wait for tomorrow's.
        (Phase.NIGHT, sept30(6, 45), local(2026, 10, 1, 6, 30)),
        (Phase.DAY, sept30(20, 40), local(2026, 10, 1, 20, 30)),
        # Night now mid to_night ramp: held until the next morning ramp.
        (Phase.NIGHT, sept30(20, 40), local(2026, 10, 1, 6, 30)),
        (Phase.DAY, sept30(6, 45), sept30(20, 30)),
    ],
)
def test_hold_expiry(held, pressed_at, expiry) -> None:
    assert fixed_schedule().hold_expiry(held, pressed_at) == expiry


def test_ramp_starts_between_is_exclusive_inclusive() -> None:
    schedule = fixed_schedule()

    assert schedule.ramp_starts_between(sept30(6, 0), sept30(21, 0)) == [
        sept30(6, 30),
        sept30(20, 30),
    ]
    assert schedule.ramp_starts_between(sept30(6, 30), sept30(20, 30)) == [
        sept30(20, 30)
    ]
    assert schedule.ramp_starts_between(sept30(7, 0), sept30(20, 0)) == []


@pytest.mark.parametrize(
    ("day", "night", "minutes", "valid"),
    [
        (dt.time(7), dt.time(21), 30, True),
        (dt.time(7), dt.time(7), 0, False),
        (dt.time(7), dt.time(7, 20), 30, False),
        (dt.time(7), dt.time(7, 20), 20, True),
        (dt.time(23, 50), dt.time(0, 10), 20, True),
        (dt.time(23, 50), dt.time(0, 10), 21, False),
        (dt.time(7), dt.time(19), 720, True),
        (dt.time(7), dt.time(19), 721, False),
    ],
)
def test_fixed_targets_valid(day, night, minutes, valid) -> None:
    assert fixed_targets_valid(day, night, dt.timedelta(minutes=minutes)) is valid


def test_fixed_targets_follow_wall_clock_across_dst() -> None:
    # US DST ends 2026-11-01 02:00 PDT -> 01:00 PST.
    schedule = fixed_schedule()

    before = schedule.next_target("day", local(2026, 10, 30, 12, 0))
    after = schedule.next_target("day", local(2026, 10, 31, 12, 0))

    assert before == dt.datetime(2026, 10, 31, 14, 0, tzinfo=dt.UTC)  # 07:00 PDT
    assert after == dt.datetime(2026, 11, 1, 15, 0, tzinfo=dt.UTC)  # 07:00 PST
    ramp = schedule.phase_at(local(2026, 11, 1, 6, 45))
    assert ramp.phase == Phase.TO_DAY
    assert ramp.progress == pytest.approx(0.5)
