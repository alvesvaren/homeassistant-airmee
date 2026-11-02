"""Reauthentication when the Airmee refresh token has expired."""

import time

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.airmee.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

from .conftest import (
    DELIVERIES_URL,
    REFRESH_URL,
    SEND_OTP_URL,
    VERIFY_OTP_URL,
    make_jwt,
)

JWT_EXPIRED = {"extraMessage": {"extraMessage": "Jwt is expired"}, "errors": {}}


def mock_otp(aioclient_mock, access_token: str) -> None:
    aioclient_mock.post(
        SEND_OTP_URL, json={"temp_token": "temp", "otp_hash_code": "hash"}
    )
    aioclient_mock.post(
        VERIFY_OTP_URL,
        json={"access_token": access_token, "refresh_token": "new-refresh"},
    )


def calls_to(aioclient_mock, url: str) -> list:
    return [call for call in aioclient_mock.mock_calls if str(call[1]) == url]


async def test_expired_refresh_token_starts_reauth(
    hass, aioclient_mock, expired_entry
):
    aioclient_mock.post(REFRESH_URL, status=400, json=JWT_EXPIRED)
    aioclient_mock.get(DELIVERIES_URL, status=401)

    await hass.config_entries.async_setup(expired_entry.entry_id)
    await hass.async_block_till_done()

    assert expired_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert calls_to(aioclient_mock, DELIVERIES_URL) == []


async def test_reauth_waits_for_user_before_sending_otp(
    hass, aioclient_mock, expired_entry
):
    mock_otp(aioclient_mock, make_jwt(int(time.time()) + 86400))

    result = await expired_entry.start_reauth_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert calls_to(aioclient_mock, SEND_OTP_URL) == []


async def test_reauth_with_otp_stores_new_tokens(
    hass, aioclient_mock, expired_entry
):
    exp = int(time.time()) + 86400
    new_access = make_jwt(exp)
    mock_otp(aioclient_mock, new_access)
    aioclient_mock.get(DELIVERIES_URL, json=[])

    result = await expired_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_otp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"otp_code": "123456"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert {
        key: expired_entry.data[key]
        for key in (CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_EXPIRES_AT)
    } == {
        CONF_ACCESS_TOKEN: new_access,
        CONF_REFRESH_TOKEN: "new-refresh",
        CONF_EXPIRES_AT: exp,
    }
    verify = calls_to(aioclient_mock, VERIFY_OTP_URL)[0]
    assert verify[2] == {
        "otp_code": "123456",
        "otp_hash_code": "hash",
        "phone_number": 701234567,
        "country_code": 46,
    }


async def test_reauth_with_wrong_otp_asks_again(hass, aioclient_mock, expired_entry):
    aioclient_mock.post(
        SEND_OTP_URL, json={"temp_token": "temp", "otp_hash_code": "hash"}
    )
    aioclient_mock.post(VERIFY_OTP_URL, status=400, json={"message": "Wrong code"})

    result = await expired_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"otp_code": "000000"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_otp"
    assert result["errors"] == {"base": "Wrong code"}
    assert expired_entry.data[CONF_ACCESS_TOKEN] == "old-access"
