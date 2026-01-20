"""Sensor platform for Underfloor Heating Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature

from .const import SUBENTRY_TYPE_ZONE, ZoneStatus
from .entity import (
    UFHControllerEntity,
    UFHControllerZoneEntity,
    get_controller_subentry_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("duty_cycle"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_error",
        translation_key="pid_error",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("error"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_proportional",
        translation_key="pid_proportional",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("p_term"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_integral",
        translation_key="pid_integral",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("i_term"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_derivative",
        translation_key="pid_derivative",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("d_term"),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator
    controller_subentry_id = get_controller_subentry_id(entry)

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
    _attr_entity_registry_visible_default = False

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

    @property
    def available(self) -> bool:
        """
        Return True if entity is available.

        Sensors are unavailable when zone is FAIL_SAFE,
        or when they have no valid value.
        """
        if not super().available:
            return False
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        zone_status = zone_data.get("zone_status", "initializing")
        if zone_status == ZoneStatus.FAIL_SAFE.value:
            return False
        return self.native_value is not None


class UFHRequestingZonesSensor(UFHControllerEntity, SensorEntity):
    """Sensor showing count of zones requesting heat."""

    _attr_translation_key = "requesting_zones"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "zones"
    _attr_entity_registry_visible_default = False

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
        return self.coordinator.data.get("zones_requesting_heat", 0)
