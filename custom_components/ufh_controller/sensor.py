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

from .entity import UFHControllerEntity, UFHControllerZoneEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


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
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator

    entities: list[SensorEntity] = [UFHRequestingZonesSensor(coordinator)]

    # Add zone-level sensors for each zone
    for zone_config in entry.options.get("zones", []):
        zone_id = zone_config["id"]
        zone_name = zone_config["name"]

        entities.extend(
            UFHZoneSensor(
                coordinator=coordinator,
                zone_id=zone_id,
                zone_name=zone_name,
                description=description,
            )
            for description in ZONE_SENSORS
        )

    async_add_entities(entities)


class UFHZoneSensor(UFHControllerZoneEntity, SensorEntity):
    """Sensor entity for zone metrics."""

    entity_description: UFHZoneSensorEntityDescription

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        description: UFHZoneSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, zone_id, zone_name)
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
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_requesting_zones"

    @property
    def native_value(self) -> int:
        """Return the count of zones requesting heat."""
        zones = self.coordinator.data.get("zones", {})
        return sum(
            1 for zone in zones.values() if zone.get("is_requesting_heat", False)
        )
