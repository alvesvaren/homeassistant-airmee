
import logging
import base64
import json
import time

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_PHONE_NUMBER,
    CONF_COUNTRY_CODE,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_EXPIRES_AT,
)

_LOGGER = logging.getLogger(__name__)


def _parse_exp_from_jwt(token: str) -> int | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload_json = json.loads(payload_bytes)
        return payload_json.get("exp")
    except Exception:
        _LOGGER.debug("Failed to parse exp from JWT", exc_info=True)
        return None


class AirmeeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._phone = None
        self._country = None
        self._temp_token = None
        self._otp_hash = None
        self._last_otp_request = 0

    async def async_step_user(self, user_input=None):
        schema = vol.Schema(
            {
                vol.Required(CONF_PHONE_NUMBER): str,
                vol.Required(CONF_COUNTRY_CODE): int,
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        self._phone = user_input[CONF_PHONE_NUMBER]
        self._country = user_input[CONF_COUNTRY_CODE]

        # dedupe
        await self.async_set_unique_id(f"{self._country}_{self._phone}")
        self._abort_if_unique_id_configured()

        # simple client-side cooldown
        now = time.time()
        if now - self._last_otp_request < 5:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors={"base": "Please wait a few seconds before requesting another OTP."},
            )
        self._last_otp_request = now

        if error := await self._send_otp():
            return self.async_show_form(step_id="user", data_schema=schema, errors={"base": error})

        return await self.async_step_otp()

    async def async_step_otp(self, user_input=None):
        schema = vol.Schema({vol.Required("otp_code"): str})

        if user_input is None:
            return self.async_show_form(step_id="otp", data_schema=schema)

        tokens, error = await self._verify_otp(user_input["otp_code"])
        if error:
            return self.async_show_form(step_id="otp", data_schema=schema, errors={"base": error})

        entry_data = {
            CONF_PHONE_NUMBER: self._phone,
            CONF_COUNTRY_CODE: self._country,
            **tokens,
        }
        return self.async_create_entry(title=f"Airmee {self._phone}", data=entry_data)

    async def _send_otp(self) -> str | None:
        """Request an SMS code. Return an error message, or None on success."""
        url = "https://api.airmee.com/customer/register/sendOtp"
        payload = {
            "phone_number": int(self._phone),
            "country_code": int(self._country),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": "TEMP_TOKEN",
        }

        session = async_get_clientsession(self.hass)
        async with session.post(url, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                return data.get("extraMessage") or data.get("message") or text or "Failed to request OTP"
            data = await resp.json()

        self._temp_token = data.get("temp_token")
        self._otp_hash = data.get("otp_hash_code")

        if not self._temp_token or not self._otp_hash:
            _LOGGER.error("Missing temp_token or otp_hash in response: %s", data)
            return "Invalid response from sendOtp"
        return None

    async def _verify_otp(self, otp_code: str) -> tuple[dict | None, str | None]:
        """Exchange the SMS code for tokens. Return (entry data, error message)."""
        url = "https://api.airmee.com/customer/register/verifyOtp"
        payload = {
            "otp_code": otp_code,
            "otp_hash_code": self._otp_hash,
            "phone_number": int(self._phone),
            "country_code": int(self._country),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._temp_token,
        }

        session = async_get_clientsession(self.hass)
        async with session.post(url, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                return None, data.get("extraMessage") or data.get("message") or text or "OTP verification failed"
            data = await resp.json()

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or not refresh_token:
            _LOGGER.error("Missing tokens in verify response: %s", data)
            return None, "Invalid response from verifyOtp"

        return {
            CONF_ACCESS_TOKEN: access_token,
            CONF_REFRESH_TOKEN: refresh_token,
            CONF_EXPIRES_AT: _parse_exp_from_jwt(access_token),
        }, None

    async def async_step_reauth(self, entry_data):
        """Start reauthentication after the refresh token has expired."""
        entry = self._get_reauth_entry()
        self._phone = entry.data[CONF_PHONE_NUMBER]
        self._country = entry.data[CONF_COUNTRY_CODE]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Wait for the user before sending the SMS, so the code is fresh."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"phone": f"+{self._country} {self._phone}"},
            )

        if error := await self._send_otp():
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"phone": f"+{self._country} {self._phone}"},
                errors={"base": error},
            )
        return await self.async_step_reauth_otp()

    async def async_step_reauth_otp(self, user_input=None):
        """Verify the SMS code and store the new tokens on the entry."""
        schema = vol.Schema({vol.Required("otp_code"): str})

        if user_input is None:
            return self.async_show_form(step_id="reauth_otp", data_schema=schema)

        tokens, error = await self._verify_otp(user_input["otp_code"])
        if error:
            return self.async_show_form(
                step_id="reauth_otp", data_schema=schema, errors={"base": error}
            )

        return self.async_update_reload_and_abort(
            self._get_reauth_entry(), data_updates=tokens
        )
