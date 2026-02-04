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

from .const import (
    ICON_GAUGE_THRESHOLDS,
    ICON_PID_ERROR_THRESHOLD,
    SUBENTRY_TYPE_ZONE,
    ZoneStatus,
)
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


def _pid_error_icon(value: float | None) -> str:
    """Return icon based on PID error value."""
    if value is None:
        return "mdi:thermometer-off"
    if value > ICON_PID_ERROR_THRESHOLD:
        return "mdi:thermometer-plus"
    if value < -ICON_PID_ERROR_THRESHOLD:
        return "mdi:thermometer-minus"
    return "mdi:thermometer-check"


def _gauge_icon(value: float | None) -> str:
    """Return gauge icon based on value."""
    if value is None:
        return "mdi:gauge-empty"
    if value >= ICON_GAUGE_THRESHOLDS[2]:
        return "mdi:gauge-full"
    if value >= ICON_GAUGE_THRESHOLDS[1]:
        return "mdi:gauge"
    if value >= ICON_GAUGE_THRESHOLDS[0]:
        return "mdi:gauge-low"
    return "mdi:gauge-empty"


@dataclass(frozen=True, kw_only=True)
class UFHZoneSensorEntityDescription(SensorEntityDescription):
    """Describes UFH zone sensor entity."""

    value_fn: Callable[[dict[str, Any]], float | None]
    icon_fn: Callable[[float | None], str] | None = None
    entity_registry_visible_default: bool = False


@dataclass(frozen=True, kw_only=True)
class UFHControllerSensorEntityDescription(SensorEntityDescription):
    """Describes UFH controller sensor entity."""

    value_fn: Callable[[dict[str, Any]], float | int | None]
    entity_registry_visible_default: bool = False


ZONE_SENSORS: tuple[UFHZoneSensorEntityDescription, ...] = (
    UFHZoneSensorEntityDescription(
        key="pid_proportional",
        translation_key="pid_proportional",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("pid_proportional"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_integral",
        translation_key="pid_integral",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("pid_integral"),
    ),
    UFHZoneSensorEntityDescription(
        key="pid_derivative",
        translation_key="pid_derivative",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("pid_derivative"),
    ),
)

PID_ERROR_SENSOR = UFHZoneSensorEntityDescription(
    key="pid_error",
    translation_key="pid_error",
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    device_class=SensorDeviceClass.TEMPERATURE,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
    value_fn=lambda data: data.get("pid_error"),
    icon_fn=_pid_error_icon,
)

DUTY_CYCLE_SENSOR = UFHZoneSensorEntityDescription(
    key="duty_cycle",
    translation_key="duty_cycle",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
    value_fn=lambda data: data.get("duty_cycle"),
    icon_fn=_gauge_icon,
)

SUPPLY_COEFFICIENT_SENSOR = UFHZoneSensorEntityDescription(
    key="supply_coefficient",
    translation_key="supply_coefficient",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=0,
    value_fn=lambda data: data.get("supply_coefficient"),
    icon_fn=_gauge_icon,
)

# Controller-level sensor descriptions
REQUESTING_ZONES_SENSOR = UFHControllerSensorEntityDescription(
    key="requesting_zones",
    translation_key="requesting_zones",
    native_unit_of_measurement="zones",
    state_class=SensorStateClass.MEASUREMENT,
    value_fn=lambda data: data.get("requesting_zones"),
)

SUPPLY_TARGET_SENSOR = UFHControllerSensorEntityDescription(
    key="supply_target_temp",
    translation_key="supply_target_temp",
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
    value_fn=lambda data: data.get("supply_target_temp"),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator
    controller_subentry_id = get_controller_subentry_id(entry)

    # Check if supply temp is configured (enables heat performance sensors)
    supply_entity = entry.data.get("supply_temp_entity")
    # Check if outdoor temp is configured (enables heating curve sensor)
    outdoor_entity = entry.data.get("outdoor_temp_entity")

    # Add controller-level sensors
    if controller_subentry_id is not None:
        controller_descriptions = [REQUESTING_ZONES_SENSOR]

        # Add supply target sensor if outdoor temp entity is configured
        if outdoor_entity:
            controller_descriptions.append(SUPPLY_TARGET_SENSOR)

        async_add_entities(
            [
                UFHControllerSensor(coordinator, controller_subentry_id, description)
                for description in controller_descriptions
            ],
            config_subentry_id=controller_subentry_id,
        )

    # Add zone-level sensors for each zone subentry
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_ZONE:
            continue
        zone_id = subentry.data["id"]
        zone_name = subentry.data["name"]
        subentry_id = subentry.subentry_id

        # Build list of descriptions for this zone
        zone_descriptions = [*ZONE_SENSORS, PID_ERROR_SENSOR, DUTY_CYCLE_SENSOR]

        # Add supply_coefficient sensor only if supply_temp_entity is configured
        if supply_entity:
            zone_descriptions.append(SUPPLY_COEFFICIENT_SENSOR)

        zone_sensors: list[SensorEntity] = [
            UFHZoneSensor(
                coordinator=coordinator,
                zone_id=zone_id,
                zone_name=zone_name,
                description=description,
                subentry_id=subentry_id,
            )
            for description in zone_descriptions
        ]

        async_add_entities(
            zone_sensors,
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
    def icon(self) -> str | None:
        """Return dynamic icon if icon_fn is defined."""
        if self.entity_description.icon_fn is not None:
            return self.entity_description.icon_fn(self.native_value)
        return None

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


class UFHControllerSensor(UFHControllerEntity, SensorEntity):
    """Generic sensor entity for controller-level metrics."""

    entity_description: UFHControllerSensorEntityDescription

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
        description: UFHControllerSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, subentry_id)
        self.entity_description = description
        self._attr_entity_registry_visible_default = (
            description.entity_registry_visible_default
        )

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{description.key}"

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value."""
        controller_data = self.coordinator.data.get("controller", {})
        return self.entity_description.value_fn(controller_data)
