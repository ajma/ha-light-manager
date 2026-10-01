"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load custom_components/ in every test that uses hass."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
