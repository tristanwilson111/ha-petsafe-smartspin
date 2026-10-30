"""Allowlisted diagnostics: never export connection data or raw device payloads."""

from homeassistant.core import HomeAssistant

from . import SmartSpinConfigEntry
from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, MIN_POLL_INTERVAL, VERSION


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SmartSpinConfigEntry,
) -> dict:
    """Exclude entry IDs, host, credentials, arbitrary nested private data and states.

    An allowlist is intentional: key-name based redaction cannot protect unknown
    nested profile fields or credentials embedded in error messages or DP strings.
    """
    coordinator = entry.runtime_data
    interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    if type(interval) is not int or interval < MIN_POLL_INTERVAL:
        interval = DEFAULT_POLL_INTERVAL
    cloud = coordinator.cloud_coordinator
    return {
        "integration_version": VERSION,
        "protocol_version": "3.5",
        "poll_interval": interval,
        "last_update_success": coordinator.last_update_success,
        "snapshot_available": coordinator.data is not None,
        "sensor_count": 10 if cloud is not None else 6,
        "cloud_enabled": cloud is not None,
        "cloud_update_success": cloud.last_update_success if cloud is not None else None,
        "cloud_auth_expired": cloud.auth_expired if cloud is not None else False,
    }
