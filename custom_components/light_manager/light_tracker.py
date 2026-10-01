"""Per-light AUTO/OVERRIDDEN state machine and report classification (spec §7).

Pure: no Home Assistant imports. The runtime feeds it readings, context IDs and
times, and acts on its answers.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, NamedTuple

from .const import (
    BRIGHTNESS_TOLERANCE,
    MIRED_TOLERANCE,
    OFF_RETURN_TO_AUTO,
    RECENT_CONTEXTS,
    SETTLE_SECONDS,
)
from .curve import LightCapabilities, LightCommand

# Spec §7.4: service data keys that make a turn-on "explicit".
EXPLICIT_KEYS = frozenset(
    {
        "brightness",
        "brightness_pct",
        "brightness_step",
        "brightness_step_pct",
        "color_temp_kelvin",
        "hs_color",
        "xy_color",
        "rgb_color",
        "rgbw_color",
        "rgbww_color",
        "color_name",
        "white",
        "profile",
    }
)
_COLOR_MODES = frozenset({"hs", "xy", "rgb", "rgbw", "rgbww"})


def is_explicit_turn_on(service: str, service_data: Mapping[str, Any]) -> bool:
    """A light.turn_on/toggle call that sets brightness, color or a profile."""
    return service in ("turn_on", "toggle") and not EXPLICIT_KEYS.isdisjoint(
        service_data
    )


class Mode(StrEnum):
    AUTO = "auto"
    OVERRIDDEN = "overridden"


@dataclass(frozen=True, slots=True)
class Reading:
    """The attributes of one light state that classification looks at."""

    brightness: int | None
    color_temp_kelvin: int | None
    color_mode: str | None

    @classmethod
    def from_attributes(cls, attrs: Mapping[str, Any]) -> Reading:
        return cls(
            attrs.get("brightness"),
            attrs.get("color_temp_kelvin"),
            attrs.get("color_mode"),
        )


class Classification(NamedTuple):
    manual: bool
    reason: str


@dataclass(frozen=True, slots=True)
class _Sent:
    """Snapshot of the command fields, to roll back a failed send."""

    expected: LightCommand | None
    pre_command: Reading | None
    sent_at: dt.datetime | None
    fade_s: float


def _mired(kelvin: float) -> float:
    return 1e6 / kelvin


@dataclass
class LightTracker:
    """One member light's automation state (spec §7.1)."""

    entity_id: str
    mode: Mode = Mode.AUTO
    overridden_at: dt.datetime | None = None
    expected: LightCommand | None = None  # last command sent
    pre_command: Reading | None = None  # reading just before that command
    sent_at: dt.datetime | None = None
    fade_s: float = 0
    _contexts: deque[str] = field(default_factory=lambda: deque(maxlen=RECENT_CONTEXTS))

    def should_send(self, command: LightCommand) -> bool:
        """AUTO lights get a command unless it equals the last one sent."""
        return self.mode is Mode.AUTO and command != self.expected

    def begin_command(
        self,
        command: LightCommand,
        context_id: str,
        now: dt.datetime,
        fade_s: float,
        current: Reading,
    ) -> _Sent:
        """Record a command about to be sent; returns a snapshot for rollback."""
        previous = _Sent(self.expected, self.pre_command, self.sent_at, self.fade_s)
        self.expected = command
        self.pre_command = current
        self.sent_at = now
        self.fade_s = fade_s
        self._contexts.append(context_id)
        return previous

    def command_failed(self, previous: _Sent) -> None:
        """Spec §10: a failed send leaves expected as it was, so it's retried."""
        self.expected = previous.expected
        self.pre_command = previous.pre_command
        self.sent_at = previous.sent_at
        self.fade_s = previous.fade_s

    def is_own_context(self, context_id: str | None) -> bool:
        return context_id is not None and context_id in self._contexts

    def mark_overridden(self, now: dt.datetime) -> None:
        self.mode = Mode.OVERRIDDEN
        self.overridden_at = now

    def reset_auto(self) -> None:
        """Back to AUTO. Forgets the last command so the target is always resent."""
        self.mode = Mode.AUTO
        self.overridden_at = None
        self.expected = None

    def on_turned_off(self, off_behavior: str) -> bool:
        """Spec §7.3. Returns True if the mode changed."""
        self.expected = None
        if self.mode is Mode.OVERRIDDEN and off_behavior == OFF_RETURN_TO_AUTO:
            self.mode = Mode.AUTO
            self.overridden_at = None
            return True
        return False

    def on_unavailable(self) -> None:
        """The light's real level is unknown; resend the target when it's back."""
        self.expected = None

    def classify(
        self,
        old: Reading,
        new: Reading,
        context_id: str | None,
        now: dt.datetime,
        caps: LightCapabilities,
    ) -> Classification:
        """Spec §7.2: is an on->on report a manual change?"""
        changed: list[str] = []
        if new.brightness is not None and new.brightness != old.brightness:
            changed.append("brightness")
        if caps.color_temp:
            if old.color_mode == "color_temp" and new.color_mode in _COLOR_MODES:
                changed.append("color_mode")
            if (
                new.color_temp_kelvin is not None
                and new.color_temp_kelvin != old.color_temp_kelvin
            ):
                changed.append("color_temp")
        if not changed:
            return Classification(False, "no tracked change")
        if self.is_own_context(context_id):
            return Classification(False, "rule 1: our context")

        reasons: list[str] = []
        for name in changed:
            if name == "color_mode":
                return Classification(True, f"color mode -> {new.color_mode}")
            if name == "brightness":
                assert new.brightness is not None
                reason = self._explain(
                    float(new.brightness),
                    self.expected.brightness if self.expected else None,
                    self.pre_command.brightness if self.pre_command else None,
                    BRIGHTNESS_TOLERANCE,
                    now,
                )
            else:
                assert new.color_temp_kelvin is not None
                expected_k = self.expected.color_temp_kelvin if self.expected else None
                pre_k = self.pre_command.color_temp_kelvin if self.pre_command else None
                reason = self._explain(
                    _mired(new.color_temp_kelvin),
                    None if expected_k is None else _mired(expected_k),
                    None if pre_k is None else _mired(pre_k),
                    MIRED_TOLERANCE,
                    now,
                )
            if reason is None:
                return Classification(True, f"{name} {self._value(name, new)}")
            reasons.append(f"{name} {reason}")
        return Classification(False, "; ".join(reasons))

    def _explain(
        self,
        value: float,
        expected: float | None,
        pre: float | None,
        tolerance: float,
        now: dt.datetime,
    ) -> str | None:
        """Rule 2 or 3 for one value; returns why it's ours, or None."""
        if expected is None:
            return None
        if abs(value - expected) <= tolerance:
            return f"rule 2: within {tolerance} of {expected:g}"
        if pre is None or self.sent_at is None:
            return None
        deadline = self.sent_at + dt.timedelta(seconds=self.fade_s + SETTLE_SECONDS)
        low, high = min(pre, expected) - tolerance, max(pre, expected) + tolerance
        if now <= deadline and low <= value <= high:
            return f"rule 3: between {pre:g} and {expected:g}"
        return None

    @staticmethod
    def _value(name: str, reading: Reading) -> str:
        if name == "brightness":
            return f"{reading.brightness}/255"
        return f"{reading.color_temp_kelvin} K"
