"""Independent, rate-limited optional cloud history polling."""

import logging
from datetime import timedelta
from time import monotonic

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CLOUD_POLL_INTERVAL, CONF_CLOUD_HISTORY, CONF_DEVICE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CloudHistoryCoordinator(DataUpdateCoordinator):
    """Keep cloud failures separate from local state; never retry passwords."""

    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_history",
            update_interval=timedelta(seconds=CLOUD_POLL_INTERVAL),
        )
        self.device_id = entry.data[CONF_DEVICE_ID]
        self._credentials = entry.data[CONF_CLOUD_HISTORY]
        self._next_allowed = 0.0
        self._failures = 0
        self.auth_expired = False

    async def _async_update_data(self):
        from .cloud_history import CloudAuthError, async_fetch_history

        if self.auth_expired:
            raise UpdateFailed(
                "Companion session expired; renew cloud history in integration options"
            )
        if monotonic() < self._next_allowed:
            if self.last_update_success and self.data is not None:
                return self.data
            raise UpdateFailed("Companion history temporarily unavailable; waiting before retry")
        self._next_allowed = monotonic() + CLOUD_POLL_INTERVAL
        try:
            snapshot = await async_fetch_history(
                async_get_clientsession(self.hass),
                credentials=self._credentials,
                device_id=self.device_id,
            )
        except CloudAuthError:
            self.auth_expired = True
            raise UpdateFailed(
                "Companion session expired; renew cloud history in integration options"
            ) from None
        except Exception:
            self._failures = min(self._failures + 1, 4)
            delay = min(CLOUD_POLL_INTERVAL * 2**self._failures, 3600)
            self._next_allowed = monotonic() + delay
            self.update_interval = timedelta(seconds=delay)
            raise UpdateFailed("Companion history read failed") from None
        self._failures = 0
        self.update_interval = timedelta(seconds=CLOUD_POLL_INTERVAL)
        return snapshot
