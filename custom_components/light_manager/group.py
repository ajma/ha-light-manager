"""GroupRuntime: drives one light group (timers, state listeners, commands, holds)."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ATTR_TRANSITION
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import (
    Context,
    Event,
    EventStateChangedData,
    HassJob,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    OFF_RETURN_TO_AUTO,
    OFF_STAY_OVERRIDDEN,
    STEP_FADE_SECONDS,
    TICK_SECONDS,
)
from .curve import (
    LightCommand,
    capabilities_from_attributes,
    effective_setpoints,
    light_command,
    setpoint_at,
)
from .light_tracker import LightTracker, Mode, Reading
from .members import expand_lights
from .models import RAMP_PHASES, GroupConfig, Phase
from .schedule import Schedule

if TYPE_CHECKING:
    from .manager import Manager

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Hold:
    """Day now / Night now: pin a phase until the next opposite ramp starts."""

    phase: Phase
    pressed_at: dt.datetime
    expiry: dt.datetime | None

    def active(self, now: dt.datetime) -> bool:
        return self.expiry is None or now < self.expiry

    def covers(self, moment: dt.datetime) -> bool:
        """True if a ramp starting at `moment` is suppressed by this hold."""
        return self.pressed_at <= moment and (
            self.expiry is None or moment < self.expiry
        )


@dataclass(frozen=True, slots=True)
class PhaseState:
    """What the phase sensor shows."""

    phase: Phase
    progress: int | None  # 0-100 during a ramp
    held: bool
    next_day_target: dt.datetime | None
    next_night_target: dt.datetime | None
    overridden_lights: list[str]


class GroupRuntime:
    """One light group: the schedule, its member lights and their trackers."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: Manager,
        subentry_id: str,
        config: GroupConfig,
        schedule: Schedule,
    ) -> None:
        self.hass = hass
        self._manager = manager
        self.subentry_id = subentry_id
        self.config = config
        self.schedule = schedule
        self.enabled = True
        self.hold: Hold | None = None
        self.trackers: dict[str, LightTracker] = {}
        self._helpers: set[str] = set()
        self._last_eval = dt_util.utcnow()
        self._listeners: list[Callable[[], None]] = []
        self._unsub_state: Callable[[], None] | None = None
        self._unsub_timer: Callable[[], None] | None = None
        self._logged_on_off: set[str] = set()
        self._retry = False  # a command failed; wake on the next tick to resend
        self._failing: set[str] = set()  # lights whose last command failed (spec §10)
        self._stopped = False  # async_stop ran; never arm the timer again

    @property
    def active(self) -> bool:
        """Spec §8: both the global switch and the group's switch are on."""
        return self._manager.global_enabled and self.enabled

    # --- lifecycle ---

    async def async_start(self, stored: dict[str, Any] | None) -> None:
        lights, helpers = expand_lights(self.hass, self.config.lights)
        self._set_members(lights, helpers)
        registry = er.async_get(self.hass)
        for entity_id in lights:
            if registry.async_get(entity_id) is None and not self.hass.states.get(
                entity_id
            ):
                _LOGGER.warning(
                    "%s: %s doesn't exist; it's skipped until it appears",
                    self.config.name,
                    entity_id,
                )
        now = dt_util.utcnow()
        self._restore(stored, now)
        self._last_eval = now
        self._schedule_next(now)
        if self.active:
            self._create_task(self._async_apply(STEP_FADE_SECONDS))

    @callback
    def async_stop(self) -> None:
        self._stopped = True
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Entities subscribe here to be told when to re-render."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # --- controls ---

    async def async_set_enabled(self, enabled: bool) -> None:
        was_active = self.active
        self.enabled = enabled
        if self.active and not was_active:
            await self.async_activate()
        self._manager.async_schedule_save()
        self._notify()

    async def async_activate(self) -> None:
        """Spec §8: on becoming active, clear overrides and apply the target."""
        self._reset_all()
        await self._async_apply(STEP_FADE_SECONDS)
        self._notify()

    async def async_press(self, phase: Phase) -> None:
        """Spec §6.5: Day now / Night now. Works even while inactive."""
        now = dt_util.utcnow()
        self.hold = Hold(phase, now, self.schedule.hold_expiry(phase, now))
        self._reset_all()
        self._schedule_next(now)
        await self._async_apply(STEP_FADE_SECONDS)
        self._manager.async_schedule_save()
        self._notify()

    # --- state for entities and storage ---

    def phase_state(self) -> PhaseState:
        now = dt_util.utcnow()
        info = self.schedule.phase_at(now)
        held = self.hold is not None and self.hold.active(now)
        if held:
            assert self.hold is not None
            phase, progress = self.hold.phase, None
        else:
            phase = info.phase
            progress = None if info.progress is None else round(info.progress * 100)
        return PhaseState(
            phase=phase,
            progress=progress,
            held=held,
            next_day_target=info.next_day_target,
            next_night_target=info.next_night_target,
            overridden_lights=sorted(
                entity_id
                for entity_id, tracker in self.trackers.items()
                if tracker.mode is Mode.OVERRIDDEN
            ),
        )

    def as_store(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hold": None
            if self.hold is None
            else {
                "phase": self.hold.phase.value,
                "pressed_at": self.hold.pressed_at.isoformat(),
            },
            "overridden": {
                entity_id: tracker.overridden_at.isoformat()
                for entity_id, tracker in self.trackers.items()
                if tracker.mode is Mode.OVERRIDDEN and tracker.overridden_at
            },
        }

    def _restore(self, stored: dict[str, Any] | None, now: dt.datetime) -> None:
        """Spec §9: restore what is still valid after a restart or reload."""
        if not stored:
            return
        self.enabled = stored.get("enabled", True)
        hold: Hold | None = None
        if (data := stored.get("hold")) and (
            pressed_at := dt_util.parse_datetime(data["pressed_at"])
        ):
            phase = Phase(data["phase"])
            hold = Hold(phase, pressed_at, self.schedule.hold_expiry(phase, pressed_at))
        self.hold = hold if hold is not None and hold.active(now) else None
        for entity_id, iso in stored.get("overridden", {}).items():
            tracker = self.trackers.get(entity_id)
            since = dt_util.parse_datetime(iso)
            if tracker is None or since is None:
                continue
            if self._cleared_by_ramp(since, now, hold):
                continue
            state = self.hass.states.get(entity_id)
            if (
                self.config.off_behavior == OFF_RETURN_TO_AUTO
                and state is not None
                and state.state == STATE_OFF
            ):
                continue
            tracker.mark_overridden(since)

    def _cleared_by_ramp(
        self, since: dt.datetime, now: dt.datetime, hold: Hold | None
    ) -> bool:
        """Spec §7.3: did a ramp start in (since, now] that no hold suppressed?"""
        return any(
            hold is None or not hold.covers(start)
            for start in self.schedule.ramp_starts_between(since, now)
        )

    # --- evaluation ---

    async def _async_on_timer(self, _scheduled: dt.datetime) -> None:
        await self._async_evaluate(dt_util.utcnow())

    async def _async_evaluate(self, now: dt.datetime) -> None:
        if self._stopped:
            return
        try:
            cleared = self._cleared_by_ramp(self._last_eval, now, self.hold)
            self._last_eval = now
            if self.hold is not None and not self.hold.active(now):
                self.hold = None
                self._manager.async_schedule_save()
            self._retry = False  # this evaluation resends to every light that needs it
            self._schedule_next(now)
            if self.active:
                if cleared:
                    self._reset_all()
                await self._async_apply(STEP_FADE_SECONDS)
        finally:
            self._notify()

    def _schedule_next(self, now: dt.datetime) -> None:
        """One timer: the next tick during a ramp, else the next ramp start.

        After a failed command, also wake on the next tick to retry it. Once the
        runtime is stopped it never arms a timer again. An evaluation arms the timer
        before its first await, so only a send that fails after the stop can still
        try to re-arm it.
        """
        if self._stopped:
            return
        info = self.schedule.phase_at(now)
        if info.phase in RAMP_PHASES and info.target is not None:
            wake = min(now + dt.timedelta(seconds=TICK_SECONDS), info.target)
        else:
            wake = info.window_start or info.target or now + dt.timedelta(days=1)
        if self._retry and self.active:
            wake = min(wake, now + dt.timedelta(seconds=TICK_SECONDS))
        if self.hold is not None and self.hold.expiry is not None:
            wake = min(wake, self.hold.expiry)
        if self._unsub_timer:
            self._unsub_timer()
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass,
            HassJob(self._async_on_timer, cancel_on_shutdown=True),
            wake,
        )

    def _effective_phase(self, now: dt.datetime) -> tuple[Phase, float | None]:
        """Spec §6.5: the held phase while a hold is active, else the schedule's."""
        if self.hold is not None and self.hold.active(now):
            return self.hold.phase, None
        info = self.schedule.phase_at(now)
        return info.phase, info.progress

    async def _async_apply(
        self, fade: float, only: Iterable[str] | None = None
    ) -> None:
        """Send the current target to AUTO lights that are on and need it."""
        if self._stopped:
            return
        now = dt_util.utcnow()
        phase, progress = self._effective_phase(now)
        targets = set(only) if only is not None else None
        sends: list[Coroutine[Any, Any, None]] = []
        for entity_id, tracker in self.trackers.items():
            if targets is not None and entity_id not in targets:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state != STATE_ON:
                continue
            day, night = effective_setpoints(
                self.config.day,
                self.config.night,
                self.config.light_overrides.get(entity_id),
            )
            pct, kelvin = setpoint_at(day, night, phase, progress)
            command = light_command(
                pct, kelvin, capabilities_from_attributes(state.attributes)
            )
            if command is None:
                if entity_id not in self._logged_on_off:
                    self._logged_on_off.add(entity_id)
                    _LOGGER.debug("%s: on/off only; never commanded", entity_id)
                continue
            if tracker.should_send(command):
                # Begin here, not inside the send: two overlapping applies must not
                # both pass should_send before either has recorded its command.
                context = Context()
                tracker.begin_command(
                    command,
                    context.id,
                    now,
                    fade,
                    Reading.from_attributes(state.attributes),
                )
                sends.append(self._async_send(tracker, command, fade, context))
        if sends:
            await asyncio.gather(*sends)

    async def _async_send(
        self,
        tracker: LightTracker,
        command: LightCommand,
        fade: float,
        context: Context,
    ) -> None:
        _LOGGER.debug("%s: send %s (fade %ss)", tracker.entity_id, command, fade)
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_ON,
                {
                    ATTR_ENTITY_ID: tracker.entity_id,
                    **command.service_data(),
                    ATTR_TRANSITION: fade,
                },
                blocking=True,
                context=context,
            )
        except Exception as err:  # any failure: keep it unconfirmed and retry
            tracker.command_failed(command, dt_util.utcnow())
            if tracker.entity_id in self._failing:
                _LOGGER.debug("%s: command failed again: %s", tracker.entity_id, err)
            else:
                self._failing.add(tracker.entity_id)
                _LOGGER.warning("%s: command failed: %s", tracker.entity_id, err)
            self._retry = True
            self._schedule_next(dt_util.utcnow())
        else:
            tracker.command_finished(command, dt_util.utcnow())
            if tracker.entity_id in self._failing:
                self._failing.discard(tracker.entity_id)
                _LOGGER.info("%s: recovered; command succeeded", tracker.entity_id)

    # --- membership and light state ---

    def _set_members(self, lights: list[str], helpers: list[str]) -> None:
        self.trackers = {
            entity_id: self.trackers.get(entity_id) or LightTracker(entity_id)
            for entity_id in lights
        }
        self._helpers = set(helpers)
        if self._unsub_state:
            self._unsub_state()
        self._unsub_state = async_track_state_change_event(
            self.hass, [*lights, *helpers], self._async_on_state
        )

    @callback
    def _refresh_members(self) -> None:
        lights, helpers = expand_lights(self.hass, self.config.lights)
        if lights == list(self.trackers) and set(helpers) == self._helpers:
            return
        added = [entity_id for entity_id in lights if entity_id not in self.trackers]
        self._set_members(lights, helpers)
        if added and self.active:
            self._create_task(self._async_apply(STEP_FADE_SECONDS, only=added))
        self._manager.async_schedule_save()
        self._notify()

    @callback
    def _async_on_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if entity_id in self._helpers:
            self._refresh_members()
            return
        tracker = self.trackers.get(entity_id)
        if tracker is None or not self.active:
            return
        old, new = event.data["old_state"], event.data["new_state"]
        old_state = old.state if old else None
        if new is None or new.state != STATE_ON:
            if new is not None and new.state == STATE_OFF:
                if tracker.on_turned_off(self.config.off_behavior, dt_util.utcnow()):
                    self._changed()
            else:
                tracker.on_unavailable()
            return
        if old_state == STATE_OFF:
            self._handle_turn_on(tracker, new.context.id)
        elif old_state == STATE_ON:
            assert old is not None
            self._handle_report(tracker, old, new)
        elif tracker.mode is Mode.AUTO:
            # unavailable/unknown/new -> on: not a turn-on; catch it up silently.
            self._create_task(self._async_apply(0, only=[entity_id]))

    def _handle_turn_on(self, tracker: LightTracker, context_id: str) -> None:
        """Spec §7.4."""
        own = tracker.is_own_context(context_id)
        if not own and self._manager.is_explicit_context(context_id):
            tracker.off_at = None  # every turn-on consumes the off
            _LOGGER.debug("%s: explicit turn-on -> overridden", tracker.entity_id)
            tracker.mark_overridden(dt_util.utcnow())
            self._changed()
            return
        if not own and self._manager.is_light_call_context(context_id):
            tracker.off_at = None  # a dashboard, voice or automation turn-on
        elif tracker.late_delivery(context_id, dt_util.utcnow()):
            _LOGGER.debug(
                "%s: our command landed after a manual off", tracker.entity_id
            )
            self._create_task(self._async_turn_off(tracker))
            return
        if tracker.mode is Mode.OVERRIDDEN:
            if self.config.off_behavior == OFF_STAY_OVERRIDDEN:
                return
            tracker.reset_auto()
            self._changed()
        self._create_task(self._async_apply(0, only=[tracker.entity_id]))

    async def _async_turn_off(self, tracker: LightTracker) -> None:
        """Spec §7.4: switch off a light that our queued command turned back on."""
        context = Context()
        tracker.add_context(context.id)
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: tracker.entity_id},
                blocking=True,
                context=context,
            )
        except Exception as err:  # no retry: the user can switch it off again
            _LOGGER.warning(
                "%s: turning off after a late command failed: %s",
                tracker.entity_id,
                err,
            )

    def _handle_report(self, tracker: LightTracker, old: State, new: State) -> None:
        """Spec §7.2: an on->on report; an AUTO light's is classified."""
        tracker.on_report()  # any report counts, an overridden light's too
        if tracker.mode is not Mode.AUTO:
            return
        result = tracker.classify(
            Reading.from_attributes(old.attributes),
            Reading.from_attributes(new.attributes),
            new.context.id,
            dt_util.utcnow(),
            capabilities_from_attributes(new.attributes),
        )
        _LOGGER.debug(
            "%s: report -> %s (%s)",
            tracker.entity_id,
            "manual" if result.manual else "ours",
            result.reason,
        )
        if result.manual:
            tracker.mark_overridden(dt_util.utcnow())
            self._changed()

    # --- helpers ---

    def _reset_all(self) -> None:
        for tracker in self.trackers.values():
            tracker.reset_auto()
        self._manager.async_schedule_save()

    def _changed(self) -> None:
        self._manager.async_schedule_save()
        self._notify()

    def _create_task(self, coro: Coroutine[Any, Any, None]) -> None:
        self._manager.entry.async_create_task(self.hass, coro)
