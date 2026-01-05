"""Binary sensor platform for UFH Controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .entity import UFHControllerZoneEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


@dataclass(frozen=True, kw_only=True)
class UFHZoneBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes UFH zone binary sensor entity."""

    value_fn: Callable[[dict[str, Any]], bool]


ZONE_BINARY_SENSORS: tuple[UFHZoneBinarySensorEntityDescription, ...] = (
    UFHZoneBinarySensorEntityDescription(
        key="blocked",
        translation_key="blocked",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: data.get("window_blocked", False),
    ),
    UFHZoneBinarySensorEntityDescription(
        key="heat_request",
        translation_key="heat_request",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda data: data.get("is_requesting_heat", False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data.coordinator

    entities: list[BinarySensorEntity] = []

    # Add zone-level binary sensors for each zone
    for zone_config in entry.options.get("zones", []):
        zone_id = zone_config["id"]
        zone_name = zone_config["name"]

        for description in ZONE_BINARY_SENSORS:
            entities.append(
                UFHZoneBinarySensor(
                    coordinator=coordinator,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    description=description,
                )
            )

    async_add_entities(entities)


class UFHZoneBinarySensor(UFHControllerZoneEntity, BinarySensorEntity):
    """Binary sensor entity for zone status."""

    entity_description: UFHZoneBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        description: UFHZoneBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator, zone_id, zone_name)
        self.entity_description = description

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{zone_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return the sensor state."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return self.entity_description.value_fn(zone_data)
