"""One serialized status poll shared by all entities."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Snapshot, poll_status
from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SmartSpinCoordinator(DataUpdateCoordinator[Snapshot]):
    """Use fresh local status only; failures make all entities unavailable."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.device_id = entry.data[CONF_DEVICE_ID]
        self.cloud_coordinator = None
        self._host = entry.data[CONF_HOST]
        self._local_key = entry.data[CONF_LOCAL_KEY]

    async def _async_update_data(self) -> Snapshot:
        try:
            return await self.hass.async_add_executor_job(
                poll_status,
                self.device_id,
                self._host,
                self._local_key,
            )
        except Exception:
            raise UpdateFailed("SmartSpin local status read failed") from None
