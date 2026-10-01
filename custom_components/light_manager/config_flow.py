"""Config flow for Light Manager: the parent entry and light-group subentries."""

from __future__ import annotations

import datetime as dt
from typing import Any

import voluptuous as vol
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    ColorTempSelector,
    ColorTempSelectorConfig,
    ColorTempSelectorUnit,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
    CONF_BRIGHTNESS_PCT,
    CONF_COLOR_TEMP_KELVIN,
    CONF_DAY,
    CONF_DAY_TARGET,
    CONF_LIGHT_OVERRIDES,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_NIGHT,
    CONF_NIGHT_TARGET,
    CONF_OFF_BEHAVIOR,
    CONF_OFFSET_MIN,
    CONF_TIME,
    CONF_TRANSITION_MIN,
    CONF_TYPE,
    DEFAULT_DAY_BRIGHTNESS_PCT,
    DEFAULT_DAY_COLOR_TEMP_KELVIN,
    DEFAULT_DAY_TIME,
    DEFAULT_NIGHT_BRIGHTNESS_PCT,
    DEFAULT_NIGHT_COLOR_TEMP_KELVIN,
    DEFAULT_NIGHT_TIME,
    DEFAULT_TRANSITION_MIN,
    DOMAIN,
    MAX_BRIGHTNESS_PCT,
    MAX_KELVIN,
    MAX_OFFSET_MIN,
    MAX_TRANSITION_MIN,
    MIN_BRIGHTNESS_PCT,
    MIN_KELVIN,
    OFF_RETURN_TO_AUTO,
    OFF_STAY_OVERRIDDEN,
    OVERRIDE_KEYS,
    SUBENTRY_TYPE_GROUP,
    TARGET_FIXED,
    TARGET_SUN,
)
from .curve import capabilities_from_attributes
from .members import expand_lights
from .schedule import fixed_targets_valid

# Flat form keys; stored data nests them (spec §5.5).
DAY_BRIGHTNESS = "day_brightness_pct"
DAY_KELVIN = "day_color_temp_kelvin"
NIGHT_BRIGHTNESS = "night_brightness_pct"
NIGHT_KELVIN = "night_color_temp_kelvin"
DAY_OFFSET = "day_offset_min"
DAY_TIME = "day_time"
NIGHT_OFFSET = "night_offset_min"
NIGHT_TIME = "night_time"
CONF_LIGHT = "light"
KELVIN_KEYS = (DAY_KELVIN, NIGHT_KELVIN)  # the *_color_temp_kelvin OVERRIDE_KEYS

SETTINGS_DEFAULTS: dict[str, Any] = {
    DAY_BRIGHTNESS: DEFAULT_DAY_BRIGHTNESS_PCT,
    DAY_KELVIN: DEFAULT_DAY_COLOR_TEMP_KELVIN,
    CONF_DAY_TARGET: TARGET_SUN,
    NIGHT_BRIGHTNESS: DEFAULT_NIGHT_BRIGHTNESS_PCT,
    NIGHT_KELVIN: DEFAULT_NIGHT_COLOR_TEMP_KELVIN,
    CONF_NIGHT_TARGET: TARGET_SUN,
    CONF_TRANSITION_MIN: DEFAULT_TRANSITION_MIN,
    CONF_OFF_BEHAVIOR: OFF_RETURN_TO_AUTO,
}
TIMING_DEFAULTS: dict[str, Any] = {
    DAY_OFFSET: 0,
    DAY_TIME: DEFAULT_DAY_TIME,
    NIGHT_OFFSET: 0,
    NIGHT_TIME: DEFAULT_NIGHT_TIME,
}


def _brightness() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_BRIGHTNESS_PCT,
            max=MAX_BRIGHTNESS_PCT,
            step=1,
            unit_of_measurement="%",
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _kelvin() -> ColorTempSelector:
    return ColorTempSelector(
        ColorTempSelectorConfig(
            unit=ColorTempSelectorUnit.KELVIN, min=MIN_KELVIN, max=MAX_KELVIN
        )
    )


def _minutes(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement="min",
            mode=NumberSelectorMode.BOX,
        )
    )


def _choice(key: str, options: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options, mode=SelectSelectorMode.LIST, translation_key=key
        )
    )


SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_LIGHTS): EntitySelector(
            EntitySelectorConfig(domain=LIGHT_DOMAIN, multiple=True)
        ),
        vol.Required(DAY_BRIGHTNESS): _brightness(),
        vol.Required(DAY_KELVIN): _kelvin(),
        vol.Required(CONF_DAY_TARGET): _choice(
            CONF_DAY_TARGET, [TARGET_SUN, TARGET_FIXED]
        ),
        vol.Required(NIGHT_BRIGHTNESS): _brightness(),
        vol.Required(NIGHT_KELVIN): _kelvin(),
        vol.Required(CONF_NIGHT_TARGET): _choice(
            CONF_NIGHT_TARGET, [TARGET_SUN, TARGET_FIXED]
        ),
        vol.Required(CONF_TRANSITION_MIN): _minutes(0, MAX_TRANSITION_MIN),
        vol.Required(CONF_OFF_BEHAVIOR): _choice(
            CONF_OFF_BEHAVIOR, [OFF_RETURN_TO_AUTO, OFF_STAY_OVERRIDDEN]
        ),
    }
)


def _timing_schema(day_type: str, night_type: str) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {}
    for kind_type, offset_key, time_key in (
        (day_type, DAY_OFFSET, DAY_TIME),
        (night_type, NIGHT_OFFSET, NIGHT_TIME),
    ):
        if kind_type == TARGET_SUN:
            fields[vol.Required(offset_key)] = _minutes(-MAX_OFFSET_MIN, MAX_OFFSET_MIN)
        else:
            fields[vol.Required(time_key)] = TimeSelector()
    return vol.Schema(fields)


def _override_schema(color_temp: bool) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {vol.Optional(DAY_BRIGHTNESS): _brightness()}
    if color_temp:
        fields[vol.Optional(DAY_KELVIN)] = _kelvin()
    fields[vol.Optional(NIGHT_BRIGHTNESS)] = _brightness()
    if color_temp:
        fields[vol.Optional(NIGHT_KELVIN)] = _kelvin()
    return vol.Schema(fields)


def _form_values(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split stored subentry data into step 1 and step 2 form values."""
    day, night = data[CONF_DAY], data[CONF_NIGHT]
    day_target, night_target = data[CONF_DAY_TARGET], data[CONF_NIGHT_TARGET]
    settings = {
        CONF_NAME: data[CONF_NAME],
        CONF_LIGHTS: data[CONF_LIGHTS],
        DAY_BRIGHTNESS: day[CONF_BRIGHTNESS_PCT],
        DAY_KELVIN: day[CONF_COLOR_TEMP_KELVIN],
        CONF_DAY_TARGET: day_target[CONF_TYPE],
        NIGHT_BRIGHTNESS: night[CONF_BRIGHTNESS_PCT],
        NIGHT_KELVIN: night[CONF_COLOR_TEMP_KELVIN],
        CONF_NIGHT_TARGET: night_target[CONF_TYPE],
        CONF_TRANSITION_MIN: data[CONF_TRANSITION_MIN],
        CONF_OFF_BEHAVIOR: data[CONF_OFF_BEHAVIOR],
    }
    timing = dict(TIMING_DEFAULTS)
    for target, offset_key, time_key in (
        (day_target, DAY_OFFSET, DAY_TIME),
        (night_target, NIGHT_OFFSET, NIGHT_TIME),
    ):
        if target[CONF_TYPE] == TARGET_SUN:
            timing[offset_key] = target.get(CONF_OFFSET_MIN, 0)
        else:
            timing[time_key] = target[CONF_TIME]
    return settings, timing


def _target(kind_type: str, offset: Any, time: Any) -> dict[str, Any]:
    if kind_type == TARGET_SUN:
        return {CONF_TYPE: TARGET_SUN, CONF_OFFSET_MIN: int(offset)}
    return {CONF_TYPE: TARGET_FIXED, CONF_TIME: time}


class LightManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """The parent entry: created with no questions (spec §5.2)."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_GROUP: GroupSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(title="Light Manager", data={})


class GroupSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a light group (spec §5.3, §5.4)."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}
        self._timing: dict[str, Any] = dict(TIMING_DEFAULTS)
        self._light: str | None = None

    # Add: step 1 -> timing.

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_settings("user", user_input, SETTINGS_DEFAULTS)

    # Reconfigure: menu -> (settings -> timing) | (customize -> customize_light).

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        settings, self._timing = _form_values(
            dict(self._get_reconfigure_subentry().data)
        )
        self._settings = settings
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["settings", "customize"],
            description_placeholders={"name": settings[CONF_NAME]},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_settings("settings", user_input, self._settings)

    async def _async_settings(
        self, step_id: str, user_input: dict[str, Any] | None, suggested: dict[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"conflicts": ""}
        if user_input is not None:
            user_input[CONF_NAME] = user_input[CONF_NAME].strip()
            errors, placeholders["conflicts"] = self._validate_settings(user_input)
            if not errors:
                self._settings = user_input
                return await self.async_step_timing()
            suggested = user_input
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(SETTINGS_SCHEMA, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _validate_settings(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], str]:
        name = user_input[CONF_NAME]
        if not name:
            return {CONF_NAME: "name_required"}, ""
        own_id = None if self.source == SOURCE_USER else self._reconfigure_subentry_id
        others = [
            sub
            for sub_id, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUBENTRY_TYPE_GROUP and sub_id != own_id
        ]
        if any(sub.data[CONF_NAME].casefold() == name.casefold() for sub in others):
            return {CONF_NAME: "name_taken"}, ""
        if not user_input[CONF_LIGHTS]:
            return {CONF_LIGHTS: "no_lights"}, ""
        mine, _ = expand_lights(self.hass, user_input[CONF_LIGHTS])
        taken: set[str] = set()
        for sub in others:
            taken.update(expand_lights(self.hass, sub.data[CONF_LIGHTS])[0])
        if conflicts := [light for light in mine if light in taken]:
            return {CONF_LIGHTS: "light_in_other_group"}, ", ".join(conflicts)
        return {}, ""

    async def async_step_timing(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        settings = self._settings
        day_type, night_type = settings[CONF_DAY_TARGET], settings[CONF_NIGHT_TARGET]
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                day_type == TARGET_FIXED
                and night_type == TARGET_FIXED
                and not fixed_targets_valid(
                    dt.time.fromisoformat(user_input[DAY_TIME]),
                    dt.time.fromisoformat(user_input[NIGHT_TIME]),
                    dt.timedelta(minutes=int(settings[CONF_TRANSITION_MIN])),
                )
            ):
                errors["base"] = "transition_too_long"
            else:
                return self._async_save(user_input)
        return self.async_show_form(
            step_id="timing",
            data_schema=self.add_suggested_values_to_schema(
                _timing_schema(day_type, night_type), user_input or self._timing
            ),
            errors=errors,
        )

    @callback
    def _async_save(self, timing: dict[str, Any]) -> SubentryFlowResult:
        settings = self._settings
        lights = list(settings[CONF_LIGHTS])
        overrides: dict[str, Any] = {}
        if self.source != SOURCE_USER:
            bulbs = set(expand_lights(self.hass, lights)[0])
            current = self._get_reconfigure_subentry().data[CONF_LIGHT_OVERRIDES]
            overrides = {eid: o for eid, o in current.items() if eid in bulbs}
        data = {
            CONF_NAME: settings[CONF_NAME],
            CONF_LIGHTS: lights,
            CONF_DAY: {
                CONF_BRIGHTNESS_PCT: int(settings[DAY_BRIGHTNESS]),
                CONF_COLOR_TEMP_KELVIN: int(settings[DAY_KELVIN]),
            },
            CONF_NIGHT: {
                CONF_BRIGHTNESS_PCT: int(settings[NIGHT_BRIGHTNESS]),
                CONF_COLOR_TEMP_KELVIN: int(settings[NIGHT_KELVIN]),
            },
            CONF_DAY_TARGET: _target(
                settings[CONF_DAY_TARGET], timing.get(DAY_OFFSET), timing.get(DAY_TIME)
            ),
            CONF_NIGHT_TARGET: _target(
                settings[CONF_NIGHT_TARGET],
                timing.get(NIGHT_OFFSET),
                timing.get(NIGHT_TIME),
            ),
            CONF_TRANSITION_MIN: int(settings[CONF_TRANSITION_MIN]),
            CONF_OFF_BEHAVIOR: settings[CONF_OFF_BEHAVIOR],
            CONF_LIGHT_OVERRIDES: overrides,
        }
        if self.source == SOURCE_USER:
            return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            title=data[CONF_NAME],
            data=data,
        )

    async def async_step_customize(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        data = self._get_reconfigure_subentry().data
        bulbs, _ = expand_lights(self.hass, data[CONF_LIGHTS])
        if not bulbs:
            return self.async_abort(reason="no_lights_to_customize")
        if user_input is not None:
            self._light = user_input[CONF_LIGHT]
            return await self.async_step_customize_light()
        overrides = data[CONF_LIGHT_OVERRIDES]
        options = [
            SelectOptionDict(value=eid, label=self._label(eid, eid in overrides))
            for eid in bulbs
        ]
        return self.async_show_form(
            step_id="customize",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LIGHT): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    def _label(self, entity_id: str, customized: bool) -> str:
        state = self.hass.states.get(entity_id)
        name = state.name if state else entity_id
        return f"{name} (customized)" if customized else name

    async def async_step_customize_light(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        assert self._light is not None
        entry, subentry = self._get_entry(), self._get_reconfigure_subentry()
        overrides = dict(subentry.data[CONF_LIGHT_OVERRIDES])
        if user_input is not None:
            values = {
                key: int(user_input[key])
                for key in OVERRIDE_KEYS
                if user_input.get(key) is not None
            }
            if values:
                overrides[self._light] = values
            else:
                overrides.pop(self._light, None)
            return self.async_update_and_abort(
                entry,
                subentry,
                data={**subentry.data, CONF_LIGHT_OVERRIDES: overrides},
            )
        state = self.hass.states.get(self._light)
        # An unavailable light has no attributes, so show the kelvin fields rather
        # than hide them. They also stay while a kelvin override is stored, so
        # saving can never silently erase it.
        color_temp = (
            state is None
            or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            or capabilities_from_attributes(state.attributes).any_color_temp
            or any(key in KELVIN_KEYS for key in overrides.get(self._light, {}))
        )
        settings = self._settings
        return self.async_show_form(
            step_id="customize_light",
            data_schema=self.add_suggested_values_to_schema(
                _override_schema(color_temp), overrides.get(self._light, {})
            ),
            description_placeholders={
                "light": self._label(self._light, customized=False),
                "day": f"{settings[DAY_BRIGHTNESS]}%, {settings[DAY_KELVIN]} K",
                "night": f"{settings[NIGHT_BRIGHTNESS]}%, {settings[NIGHT_KELVIN]} K",
            },
        )
