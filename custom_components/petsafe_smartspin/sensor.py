"""Six read-only sensors, with shared availability and device identity."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SmartSpinConfigEntry
from .const import DOMAIN
from .coordinator import SmartSpinCoordinator

DESCRIPTIONS = (
    SensorEntityDescription(key="status", translation_key="status"),
    SensorEntityDescription(key="fault", translation_key="fault"),
    SensorEntityDescription(
        key="clean_control_state", translation_key="clean_control_state"
    ),
    SensorEntityDescription(key="history_record", translation_key="history_record"),
    SensorEntityDescription(key="visits_today", translation_key="visits_today"),
    SensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartSpinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        SmartSpinSensor(entry.runtime_data, description) for description in DESCRIPTIONS
    )


class SmartSpinSensor(CoordinatorEntity[SmartSpinCoordinator], SensorEntity):
    """Expose raw, proven DP meanings, without interpreting fault bits or events."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SmartSpinCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name="ScoopFree SmartSpin",
            manufacturer="PetSafe",
            model="ScoopFree SmartSpin",
        )

    @property
    def native_value(self):
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        return getattr(self.coordinator.data, self.entity_description.key)
