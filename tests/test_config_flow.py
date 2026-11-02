"""Initial setup with phone number and SMS code."""

import time

from homeassistant.data_entry_flow import FlowResultType

from custom_components.airmee.const import DOMAIN

from .conftest import DELIVERIES_URL, SEND_OTP_URL, VERIFY_OTP_URL, make_jwt


async def test_user_flow_creates_entry(hass, aioclient_mock):
    exp = int(time.time()) + 86400
    access = make_jwt(exp)
    aioclient_mock.post(
        SEND_OTP_URL, json={"temp_token": "temp", "otp_hash_code": "hash"}
    )
    aioclient_mock.post(
        VERIFY_OTP_URL, json={"access_token": access, "refresh_token": "refresh"}
    )
    aioclient_mock.get(DELIVERIES_URL, json=[])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone_number": "701234567", "country_code": 46}
    )
    assert result["step_id"] == "otp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"otp_code": "123456"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Airmee 701234567"
    assert result["data"] == {
        "phone_number": "701234567",
        "country_code": 46,
        "access_token": access,
        "refresh_token": "refresh",
        "expires_at": exp,
    }
