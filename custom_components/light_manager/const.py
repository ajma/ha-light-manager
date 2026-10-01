"""Constants for Light Manager."""

from typing import Final

DOMAIN: Final = "light_manager"
SUBENTRY_TYPE_GROUP: Final = "group"

# Subentry data keys (spec §5.5)
CONF_NAME: Final = "name"
CONF_LIGHTS: Final = "lights"
CONF_DAY: Final = "day"
CONF_NIGHT: Final = "night"
CONF_BRIGHTNESS_PCT: Final = "brightness_pct"
CONF_COLOR_TEMP_KELVIN: Final = "color_temp_kelvin"
CONF_DAY_TARGET: Final = "day_target"
CONF_NIGHT_TARGET: Final = "night_target"
CONF_TYPE: Final = "type"
CONF_OFFSET_MIN: Final = "offset_min"
CONF_TIME: Final = "time"
CONF_TRANSITION_MIN: Final = "transition_min"
CONF_OFF_BEHAVIOR: Final = "off_behavior"
CONF_LIGHT_OVERRIDES: Final = "light_overrides"

TARGET_SUN: Final = "sun"
TARGET_FIXED: Final = "fixed"

OFF_RETURN_TO_AUTO: Final = "return_to_auto"
OFF_STAY_OVERRIDDEN: Final = "stay_overridden"

OVERRIDE_KEYS: Final = (
    "day_brightness_pct",
    "day_color_temp_kelvin",
    "night_brightness_pct",
    "night_color_temp_kelvin",
)

# Defaults (spec §5.3)
DEFAULT_DAY_BRIGHTNESS_PCT: Final = 100
DEFAULT_DAY_COLOR_TEMP_KELVIN: Final = 4000
DEFAULT_NIGHT_BRIGHTNESS_PCT: Final = 20
DEFAULT_NIGHT_COLOR_TEMP_KELVIN: Final = 2200
DEFAULT_TRANSITION_MIN: Final = 30
DEFAULT_DAY_TIME: Final = "07:00:00"
DEFAULT_NIGHT_TIME: Final = "21:00:00"

# Ranges (spec §5.3)
MIN_BRIGHTNESS_PCT: Final = 1
MAX_BRIGHTNESS_PCT: Final = 100
MIN_KELVIN: Final = 1500
MAX_KELVIN: Final = 6500
MAX_OFFSET_MIN: Final = 180
MAX_TRANSITION_MIN: Final = 180

# Tuning (spec §6.4, §7.2): adjust against real hardware
TICK_SECONDS: Final = 30
STEP_FADE_SECONDS: Final = 2
SETTLE_SECONDS: Final = 10
BRIGHTNESS_TOLERANCE: Final = 5  # of 255
MIRED_TOLERANCE: Final = 10
EXPLICIT_CONTEXT_SECONDS: Final = 10
RECENT_CONTEXTS: Final = 5

# Persistence (spec §9)
STORAGE_VERSION: Final = 1
SAVE_DELAY_SECONDS: Final = 1
