import asyncio
import logging
from datetime import datetime, timezone, timedelta
import base64
import json

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    DEFAULT_POLL_INTERVAL,
    SHORT_POLL_INTERVAL,
    SOON_THRESHOLD,
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
    except Exception:  # pragma: no cover
        _LOGGER.debug("Failed to parse exp from JWT", exc_info=True)
        return None


class AirmeeDataUpdateCoordinator(DataUpdateCoordinator):
    REFRESH_URL = "https://api.airmee.com/customer/register/refreshToken"

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._access_token = entry.data[CONF_ACCESS_TOKEN]
        self._refresh_token = entry.data[CONF_REFRESH_TOKEN]
        self._expires_at = entry.data.get(CONF_EXPIRES_AT)
        super().__init__(
            hass,
            _LOGGER,
            name="airmee",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )

    async def _async_setup(self):
        return

    async def _async_update_data(self):
        await self._ensure_token_valid()

        url = "https://api.airmee.com/customer/deliveries"
        headers = {"Authorization": self._access_token}

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, headers=headers, timeout=30) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Unauthorized fetching deliveries")
                if resp.status != 200:
                    text = await resp.text()
                    raise UpdateFailed(f"Failed fetching deliveries: {resp.status} {text}")
                data = await resp.json()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching deliveries: {err}") from err

        # adaptive polling: speed up if next package is soon
        next_eta_ts = None
        if data and isinstance(data, list):
            now_ts = int(datetime.now(tz=timezone.utc).timestamp())
            valid = [
                p
                for p in data
                if p.get("dropoff_eta") and int(p.get("dropoff_eta")) >= now_ts
            ]
            if valid:
                soonest = min(valid, key=lambda p: int(p.get("dropoff_eta")))
                eta = soonest.get("dropoff_eta")
                if eta:
                    next_eta_ts = int(eta)

        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        if next_eta_ts and (next_eta_ts - now_ts) < SOON_THRESHOLD:
            self.update_interval = timedelta(seconds=SHORT_POLL_INTERVAL)
        else:
            self.update_interval = timedelta(seconds=DEFAULT_POLL_INTERVAL)

        return data

    async def _ensure_token_valid(self):
        if not self._expires_at:
            return
        now = int(datetime.now(tz=timezone.utc).timestamp())
        if self._expires_at - now < 60:
            await self.async_refresh_token()

    async def async_refresh_token(self):
        _LOGGER.debug("Refreshing Airmee tokens using refresh endpoint")
        session = async_get_clientsession(self.hass)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "TEMP_TOKEN",
        }
        payload = {"refresh_token": self._refresh_token}
        try:
            async with session.post(self.REFRESH_URL, json=payload, headers=headers, timeout=30) as resp:
                text = await resp.text()
                if resp.status == 401:
                    _LOGGER.warning("Refresh token invalid, need reauth: %s", text)
                    raise ConfigEntryAuthFailed("Refresh token invalid")
                if resp.status != 200:
                    _LOGGER.error("Failed to refresh token: %s %s", resp.status, text)
                    return
                data = await resp.json()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.error("Exception refreshing token: %s", err)
            return

        new_access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if not new_access or not new_refresh:
            _LOGGER.error("Refresh endpoint returned incomplete token payload: %s", data)
            return

        new_expires_at = _parse_exp_from_jwt(new_access)

        # update internal cache
        self._access_token = new_access
        self._refresh_token = new_refresh
        self._expires_at = new_expires_at

        # persist updated tokens and expiry
        updated = self.entry.data.copy()
        updated.update(
            {
                CONF_ACCESS_TOKEN: new_access,
                CONF_REFRESH_TOKEN: new_refresh,
                CONF_EXPIRES_AT: new_expires_at,
            }
        )
        await self.entry.async_update(data=updated)
