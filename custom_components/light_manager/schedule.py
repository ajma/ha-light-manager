"""Schedule math: phases, ramp windows and hold expiry. Pure: no HA imports.

All datetimes are timezone-aware. Sun times come from an injected callable so
tests can use fixed sunrise/sunset times.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .const import TARGET_FIXED
from .models import Phase, TargetTime

type SunProvider = Callable[[dt.date, str], dt.datetime | None]
"""(local date, "sunrise" | "sunset") -> aware datetime, or None if no event."""

type Kind = Literal["day", "night"]

_SUN_EVENT: dict[Kind, str] = {"day": "sunrise", "night": "sunset"}
_OPPOSITE: dict[Kind, Kind] = {"day": "night", "night": "day"}
_RAMP: dict[Kind, Phase] = {"day": Phase.TO_DAY, "night": Phase.TO_NIGHT}
_PLATEAU: dict[Kind, Phase] = {"day": Phase.DAY, "night": Phase.NIGHT}
# Look this many days ahead/back for a target: first a short search, then a
# year (polar regions can go months without a sunrise or sunset).
_SEARCH_DAYS = (2, 370)


@dataclass(frozen=True, slots=True)
class PhaseInfo:
    """The schedule's answer for one moment."""

    phase: Phase
    progress: float | None  # 0..1 during a ramp, else None
    window_start: dt.datetime | None  # start of the upcoming/current ramp
    target: dt.datetime | None  # the next target (end of that ramp)
    next_day_target: dt.datetime | None
    next_night_target: dt.datetime | None


def fixed_targets_valid(day: dt.time, night: dt.time, transition: dt.timedelta) -> bool:
    """Spec §5.3: fixed targets differ and are at least a transition apart."""
    day_s = day.hour * 3600 + day.minute * 60 + day.second
    night_s = night.hour * 3600 + night.minute * 60 + night.second
    gap = abs(day_s - night_s)
    if gap == 0:
        return False
    return min(gap, 86400 - gap) >= transition.total_seconds()


def _earlier_kind(day: dt.datetime | None, night: dt.datetime | None) -> Kind:
    """Which of two optional moments comes first (day wins ties; None is last)."""
    if night is None or (day is not None and day <= night):
        return "day"
    return "night"


class Schedule:
    """Computes target times, ramp windows and phases for one group."""

    def __init__(
        self,
        day_target: TargetTime,
        night_target: TargetTime,
        transition: dt.timedelta,
        sun: SunProvider,
        tz: dt.tzinfo,
    ) -> None:
        self._targets: dict[Kind, TargetTime] = {
            "day": day_target,
            "night": night_target,
        }
        self._transition = transition
        self._sun = sun
        self._tz = tz

    def _on_date(self, kind: Kind, day: dt.date) -> dt.datetime | None:
        """The kind's target for a local date, or None if the sun event is missing."""
        target = self._targets[kind]
        if target.type == TARGET_FIXED:
            assert target.time is not None
            return dt.datetime.combine(day, target.time, self._tz).astimezone(dt.UTC)
        event = self._sun(day, _SUN_EVENT[kind])
        return None if event is None else event + target.offset

    def _between(
        self, kind: Kind, start: dt.datetime, end: dt.datetime
    ) -> list[dt.datetime]:
        """All targets of a kind with start <= t <= end, ascending."""
        day = start.astimezone(self._tz).date() - dt.timedelta(days=1)
        last = end.astimezone(self._tz).date() + dt.timedelta(days=1)
        found: list[dt.datetime] = []
        while day <= last:
            moment = self._on_date(kind, day)
            if moment is not None and start <= moment <= end:
                found.append(moment)
            day += dt.timedelta(days=1)
        return sorted(found)

    def next_target(self, kind: Kind, after: dt.datetime) -> dt.datetime | None:
        """The first target of a kind strictly after a moment."""
        for days in _SEARCH_DAYS:
            end = after + dt.timedelta(days=days)
            found = [t for t in self._between(kind, after, end) if t > after]
            if found:
                return found[0]
        return None

    def _last_target(
        self, kind: Kind, moment: dt.datetime, *, inclusive: bool
    ) -> dt.datetime | None:
        """The latest target of a kind before (or at, if inclusive) a moment."""
        for days in _SEARCH_DAYS:
            start = moment - dt.timedelta(days=days)
            found = [
                t
                for t in self._between(kind, start, moment)
                if t < moment or (inclusive and t == moment)
            ]
            if found:
                return found[-1]
        return None

    def window_start(self, kind: Kind, target: dt.datetime) -> dt.datetime:
        """Spec §6.2: max(target - transition, previous opposite target)."""
        start = target - self._transition
        previous = self._last_target(_OPPOSITE[kind], target, inclusive=False)
        if previous is not None and previous > start:
            start = previous
        return start

    def phase_at(self, now: dt.datetime) -> PhaseInfo:
        """Spec §6.2: the phase from the clock alone."""
        next_day = self.next_target("day", now)
        next_night = self.next_target("night", now)
        if next_day is None and next_night is None:
            return PhaseInfo(Phase.DAY, None, None, None, None, None)
        kind = _earlier_kind(next_day, next_night)
        target = next_day if kind == "day" else next_night
        assert target is not None

        # Targets normally alternate. If the latest one was the same kind (a
        # sun event didn't occur), we already arrived: stay, with no ramp.
        last_day = self._last_target("day", now, inclusive=True)
        last_night = self._last_target("night", now, inclusive=True)
        if last_day is not None or last_night is not None:
            if last_night is None or (last_day is not None and last_day > last_night):
                last_kind = "day"
            else:
                last_kind = "night"
            if last_kind == kind:
                return PhaseInfo(
                    _PLATEAU[kind], None, None, target, next_day, next_night
                )

        start = self.window_start(kind, target)
        if start <= now < target:
            progress = (now - start) / (target - start)
            return PhaseInfo(_RAMP[kind], progress, start, target, next_day, next_night)
        return PhaseInfo(
            _PLATEAU[_OPPOSITE[kind]], None, start, target, next_day, next_night
        )

    def hold_expiry(self, held: Phase, pressed_at: dt.datetime) -> dt.datetime | None:
        """Spec §6.5: the first opposite ramp start strictly after the press.

        Night now waits for the next to_day ramp; Day now for the next to_night.
        """
        kind: Kind = "day" if held == Phase.NIGHT else "night"
        moment = pressed_at
        for _ in range(3):
            target = self.next_target(kind, moment)
            if target is None:
                return None
            start = self.window_start(kind, target)
            if start > pressed_at:
                return start
            moment = target
        return None

    def ramp_starts_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[dt.datetime]:
        """Every ramp window start s (either kind) with start < s <= end."""
        found: list[dt.datetime] = []
        for kind in ("day", "night"):
            for target in self._between(kind, start, end + self._transition):
                window = self.window_start(kind, target)
                if start < window <= end:
                    found.append(window)
        return sorted(found)
