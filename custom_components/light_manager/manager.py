"""Manager: owns the group runtimes, global controls and persistence."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import Any

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    EVENT_CALL_SERVICE,
    SERVICE_TOGGLE,
    SERVICE_TURN_ON,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EXPLICIT_CONTEXT_SECONDS,
    SAVE_DELAY_SECONDS,
    STORAGE_VERSION,
    SUBENTRY_TYPE_GROUP,
)
from .group import GroupRuntime
from .light_tracker import is_explicit_turn_on
from .models import GroupConfig, Phase
from .schedule import Schedule


class Manager:
    """Everything one Light Manager config entry runs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.global_enabled = True
        self.groups: dict[str, GroupRuntime] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        # light.turn_on/toggle calls by context ID: (when, whether it set values)
        self._calls: dict[str, tuple[dt.datetime, bool]] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsub_call_service: Callable[[], None] | None = None
        self._stopped = False  # async_stop ran; nothing may save or run after it

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.global_enabled = stored.get("global_enabled", True)
        tz = dt_util.get_default_time_zone()
        for subentry_id, subentry in self.entry.subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_GROUP:
                continue
            config = GroupConfig.from_data(subentry.data)
            schedule = Schedule(
                config.day_target,
                config.night_target,
                config.transition,
                self._sun,
                tz,
            )
            self.groups[subentry_id] = GroupRuntime(
                self.hass, self, subentry_id, config, schedule
            )
        self._unsub_call_service = self.hass.bus.async_listen(
            EVENT_CALL_SERVICE, self._async_on_call_service
        )
        stored_groups = stored.get("groups", {})
        for subentry_id, runtime in self.groups.items():
            await runtime.async_start(stored_groups.get(subentry_id))
        self.async_schedule_save()  # drops groups that no longer exist

    async def async_stop(self) -> None:
        self._stopped = True
        if self._unsub_call_service:
            self._unsub_call_service()
            self._unsub_call_service = None
        for runtime in self.groups.values():
            runtime.async_stop()
        await self._store.async_save(self._snapshot())

    def _sun(self, day: dt.date, event: str) -> dt.datetime | None:
        return get_astral_event_date(self.hass, event, day)

    # --- persistence ---

    def _snapshot(self) -> dict[str, Any]:
        return {
            "global_enabled": self.global_enabled,
            "groups": {
                subentry_id: runtime.as_store()
                for subentry_id, runtime in self.groups.items()
            },
        }

    @callback
    def async_schedule_save(self) -> None:
        # An old runtime's delayed save would overwrite the new one's: same key.
        if self._stopped:
            return
        self._store.async_delay_save(self._snapshot, SAVE_DELAY_SECONDS)

    # --- turn-on call detection (spec §7.4) ---

    @callback
    def _async_on_call_service(self, event: Event) -> None:
        data = event.data
        service = data.get(ATTR_SERVICE, "")
        if data.get(ATTR_DOMAIN) != LIGHT_DOMAIN or service not in (
            SERVICE_TURN_ON,
            SERVICE_TOGGLE,
        ):
            return
        now = dt_util.utcnow()
        cutoff = now - dt.timedelta(seconds=EXPLICIT_CONTEXT_SECONDS)
        self._calls = {
            context_id: call
            for context_id, call in self._calls.items()
            if call[0] > cutoff
        }
        explicit = is_explicit_turn_on(service, data.get(ATTR_SERVICE_DATA) or {})
        # One context can make several calls; any explicit one makes it explicit.
        explicit |= self._calls.get(event.context.id, (now, False))[1]
        self._calls[event.context.id] = (now, explicit)

    def is_explicit_context(self, context_id: str | None) -> bool:
        """Was this context a recent light.turn_on/toggle that set values?"""
        return self._recent_call(context_id, explicit_only=True)

    def is_light_call_context(self, context_id: str | None) -> bool:
        """Was this context any recent light.turn_on/toggle call?"""
        return self._recent_call(context_id, explicit_only=False)

    def _recent_call(self, context_id: str | None, *, explicit_only: bool) -> bool:
        call = self._calls.get(context_id) if context_id else None
        if call is None:
            return False
        at, explicit = call
        return (explicit or not explicit_only) and dt_util.utcnow() - at <= (
            dt.timedelta(seconds=EXPLICIT_CONTEXT_SECONDS)
        )

    # --- global controls (spec §8) ---

    async def async_set_global_enabled(self, enabled: bool) -> None:
        was_active = {sid for sid, runtime in self.groups.items() if runtime.active}
        self.global_enabled = enabled
        for subentry_id, runtime in self.groups.items():
            if runtime.active and subentry_id not in was_active:
                await runtime.async_activate()
        self.async_schedule_save()
        self._notify()

    async def async_press_all(self, phase: Phase) -> None:
        """Global Day now / Night now: every group whose own switch is on."""
        await asyncio.gather(
            *(
                runtime.async_press(phase)
                for runtime in self.groups.values()
                if runtime.enabled
            )
        )

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
