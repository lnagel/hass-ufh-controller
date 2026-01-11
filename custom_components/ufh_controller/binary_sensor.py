"""Binary sensor platform for Underfloor Heating Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .const import SUBENTRY_TYPE_ZONE, ControllerStatus, ZoneStatus
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
class UFHZoneBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes UFH zone binary sensor entity."""

    value_fn: Callable[[dict[str, Any]], bool]


ZONE_BINARY_SENSORS: tuple[UFHZoneBinarySensorEntityDescription, ...] = (
    UFHZoneBinarySensorEntityDescription(
        key="blocked",
        translation_key="blocked",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: data.get("blocked", False),
    ),
    UFHZoneBinarySensorEntityDescription(
        key="heat_request",
        translation_key="heat_request",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda data: data.get("heat_request", False),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data.coordinator

    # Add controller-level sensors
    controller_subentry_id = get_controller_subentry_id(entry)
    if controller_subentry_id is not None:
        entities: list[BinarySensorEntity] = [
            UFHControllerStatusSensor(coordinator, controller_subentry_id)
        ]

        # Only create flush_request sensor if DHW entity is configured
        if entry.data.get("dhw_active_entity"):
            entities.append(UFHFlushRequestSensor(coordinator, controller_subentry_id))

        async_add_entities(entities, config_subentry_id=controller_subentry_id)

    # Add zone-level binary sensors for each zone subentry
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_ZONE:
            continue
        zone_id = subentry.data["id"]
        zone_name = subentry.data["name"]
        subentry_id = subentry.subentry_id

        async_add_entities(
            [
                UFHZoneBinarySensor(
                    coordinator=coordinator,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    description=description,
                    subentry_id=subentry_id,
                )
                for description in ZONE_BINARY_SENSORS
            ],
            config_subentry_id=subentry_id,
        )


class UFHZoneBinarySensor(UFHControllerZoneEntity, BinarySensorEntity):
    """Binary sensor entity for zone status."""

    entity_description: UFHZoneBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        description: UFHZoneBinarySensorEntityDescription,
        subentry_id: str,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator, zone_id, zone_name, subentry_id)
        self.entity_description = description

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{zone_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return the sensor state."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return self.entity_description.value_fn(zone_data)

    @property
    def available(self) -> bool:
        """
        Return True if entity is available.

        Binary sensors are unavailable when zone is INITIALIZING or FAIL_SAFE.
        """
        if not super().available:
            return False
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        zone_status = zone_data.get("zone_status", "initializing")
        return zone_status not in (
            ZoneStatus.INITIALIZING.value,
            ZoneStatus.FAIL_SAFE.value,
        )


class UFHControllerStatusSensor(UFHControllerEntity, BinarySensorEntity):
    """
    Binary sensor indicating controller operational status.

    This sensor is ON when there is a problem (degraded or fail-safe mode),
    and OFF when the controller is operating normally.
    """

    _attr_translation_key = "status"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator, subentry_id)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_status"

    @property
    def is_on(self) -> bool:
        """Return True if there is a problem (degraded or fail-safe)."""
        return self.coordinator.status in (
            ControllerStatus.DEGRADED,
            ControllerStatus.FAIL_SAFE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional status attributes."""
        return {
            "controller_status": self.coordinator.status.value,
            "zones_degraded": self.coordinator.data.get("zones_degraded", 0),
            "zones_fail_safe": self.coordinator.data.get("zones_fail_safe", 0),
        }


class UFHFlushRequestSensor(UFHControllerEntity, BinarySensorEntity):
    """
    Binary sensor indicating when flush is actively requested.

    This sensor is ON when:
    - DHW is active AND flush_enabled is ON, OR
    - Post-DHW flush period is active AND flush_enabled is ON
    """

    _attr_translation_key = "flush_request"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_name = "Flush Request"

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the flush request sensor."""
        super().__init__(coordinator, subentry_id)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_flush_request"

    @property
    def is_on(self) -> bool:
        """Return True if flush is currently requested."""
        # Only return True if flush_enabled is also True
        if not self.coordinator.controller.state.flush_enabled:
            return False
        return self.coordinator.data.get("flush_request", False)
