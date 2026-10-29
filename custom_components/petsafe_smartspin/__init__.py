"""Experimental, read-only PetSafe SmartSpin integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SmartSpinCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SENSOR]
type SmartSpinConfigEntry = ConfigEntry[SmartSpinCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SmartSpinConfigEntry) -> bool:
    """Validate the first status and forward the six sensors."""
    coordinator = SmartSpinCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SmartSpinConfigEntry) -> bool:
    """Unloading entities removes coordinator listeners and polling."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: SmartSpinConfigEntry) -> None:
    """Apply options and verified credential changes with a scoped reload."""
    await hass.config_entries.async_reload(entry.entry_id)
