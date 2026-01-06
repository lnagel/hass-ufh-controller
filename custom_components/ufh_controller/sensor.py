"""Sensor platform for UFH Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)

from .const import SUBENTRY_TYPE_CONTROLLER, SUBENTRY_TYPE_ZONE
from .entity import UFHControllerEntity, UFHControllerZoneEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


def _get_controller_subentry_id(entry: UFHControllerConfigEntry) -> str | None:
    """Get the controller subentry ID."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            return subentry.subentry_id
    return None


@dataclass(frozen=True, kw_only=True)
class UFHZoneSensorEntityDescription(SensorEntityDescription):
    """Describes UFH zone sensor entity."""

    value_fn: Callable[[dict[str, Any]], float | None]


ZONE_SENSORS: tuple[UFHZoneSensorEntityDescription, ...] = (
    UFHZoneSensorEntityDescription(
        key="duty_cycle",
        translation_key="duty_cycle",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("duty_cycle"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_error",
        translation_key="pid_error",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("error"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_proportional",
        translation_key="pid_proportional",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("p_term"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_integral",
        translation_key="pid_integral",
        native_unit_of_measurement="°C·s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("integral"),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator
    controller_subentry_id = _get_controller_subentry_id(entry)

    # Add controller-level sensors
    if controller_subentry_id is not None:
        async_add_entities(
            [UFHRequestingZonesSensor(coordinator, controller_subentry_id)],
            config_subentry_id=controller_subentry_id,
        )

    # Add zone-level sensors for each zone subentry
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_ZONE:
            continue
        zone_id = subentry.data["id"]
        zone_name = subentry.data["name"]
        subentry_id = subentry.subentry_id

        async_add_entities(
            [
                UFHZoneSensor(
                    coordinator=coordinator,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    description=description,
                    subentry_id=subentry_id,
                )
                for description in ZONE_SENSORS
            ],
            config_subentry_id=subentry_id,
        )


class UFHZoneSensor(UFHControllerZoneEntity, SensorEntity):
    """Sensor entity for zone metrics."""

    entity_description: UFHZoneSensorEntityDescription

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        description: UFHZoneSensorEntityDescription,
        subentry_id: str,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, zone_id, zone_name, subentry_id)
        self.entity_description = description

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{zone_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return self.entity_description.value_fn(zone_data)


class UFHRequestingZonesSensor(UFHControllerEntity, SensorEntity):
    """Sensor showing count of zones requesting heat."""

    _attr_translation_key = "requesting_zones"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "zones"

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, subentry_id)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_requesting_zones"

    @property
    def native_value(self) -> int:
        """Return the count of zones requesting heat."""
        zones = self.coordinator.data.get("zones", {})
        return sum(
            1 for zone in zones.values() if zone.get("is_requesting_heat", False)
        )
