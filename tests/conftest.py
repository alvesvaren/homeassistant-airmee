"""Shared fixtures for the Airmee tests."""

import base64
import json
import time

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airmee.const import (
    CONF_ACCESS_TOKEN,
    CONF_COUNTRY_CODE,
    CONF_EXPIRES_AT,
    CONF_PHONE_NUMBER,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

API = "https://api.airmee.com"
SEND_OTP_URL = f"{API}/customer/register/sendOtp"
VERIFY_OTP_URL = f"{API}/customer/register/verifyOtp"
REFRESH_URL = f"{API}/customer/register/refreshToken"
DELIVERIES_URL = f"{API}/customer/deliveries"


def make_jwt(exp: int) -> str:
    """Build an unsigned JWT that only carries an exp claim."""

    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/airmee."""
    yield


@pytest.fixture
def expired_entry(hass) -> MockConfigEntry:
    """A config entry whose access token has expired."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Airmee 701234567",
        unique_id="46_701234567",
        data={
            CONF_PHONE_NUMBER: "701234567",
            CONF_COUNTRY_CODE: 46,
            CONF_ACCESS_TOKEN: "old-access",
            CONF_REFRESH_TOKEN: "old-refresh",
            CONF_EXPIRES_AT: int(time.time()) - 3600,
        },
    )
    entry.add_to_hass(hass)
    return entry
