"""Six read-only sensors, with shared availability and device identity."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SmartSpinConfigEntry
from .const import DOMAIN
from .coordinator import SmartSpinCoordinator

DESCRIPTIONS = (
    SensorEntityDescription(key="status", translation_key="status"),
    SensorEntityDescription(key="fault", translation_key="fault"),
    SensorEntityDescription(key="clean_control_state", translation_key="clean_control_state"),
    SensorEntityDescription(key="history_record", translation_key="history_record"),
    SensorEntityDescription(key="visits_today", translation_key="visits_today"),
    SensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


CLOUD_DESCRIPTIONS = (
    SensorEntityDescription(
        key="last_visit_weight",
        translation_key="last_visit_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="last_visit_duration",
        translation_key="last_visit_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    SensorEntityDescription(
        key="last_visit", translation_key="last_visit", device_class=SensorDeviceClass.TIMESTAMP
    ),
    SensorEntityDescription(
        key="cloud_last_checked",
        translation_key="cloud_last_checked",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
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
    if entry.runtime_data.cloud_coordinator is not None:
        async_add_entities(
            SmartSpinCloudSensor(entry.runtime_data.cloud_coordinator, description)
            for description in CLOUD_DESCRIPTIONS
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


class SmartSpinCloudSensor(SmartSpinSensor):
    """Last reported visit, not a live scale reading or cat identity."""

    @property
    def native_value(self):
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        data = self.coordinator.data
        key = self.entity_description.key
        if key == "cloud_last_checked":
            return data.fetched_at
        if not data.visits:
            return None
        visit = data.visits[0]
        return {
            "last_visit_weight": visit.weight_kg,
            "last_visit_duration": visit.duration_seconds,
            "last_visit": visit.timestamp,
        }[key]

    @property
    def extra_state_attributes(self):
        if (
            self.entity_description.key != "last_visit"
            or not self.coordinator.last_update_success
            or self.coordinator.data is None
        ):
            return None
        return {
            "recent_visits": [
                {
                    "time": visit.timestamp.isoformat(),
                    "weight_kg": visit.weight_kg,
                    "duration_seconds": visit.duration_seconds,
                }
                for visit in self.coordinator.data.visits[:10]
            ]
        }
