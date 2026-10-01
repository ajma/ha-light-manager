"""Config flow for Light Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class LightManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """The parent entry: created with no questions (spec §5.2)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(title="Light Manager", data={})
