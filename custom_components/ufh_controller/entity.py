"""Base entity classes for UFH Controller."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import UFHControllerDataUpdateCoordinator
from .device import get_controller_device_info, get_zone_device_info


class UFHControllerEntity(CoordinatorEntity[UFHControllerDataUpdateCoordinator]):
    """Base class for controller-level UFH Controller entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_config_subentry_id = subentry_id
        self._attr_device_info = get_controller_device_info(coordinator)


class UFHControllerZoneEntity(CoordinatorEntity[UFHControllerDataUpdateCoordinator]):
    """Base class for zone-level UFH Controller entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        subentry_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._attr_config_subentry_id = subentry_id
        self._attr_device_info = get_zone_device_info(
            coordinator, zone_id, zone_name, subentry_id
        )

    @property
    def zone_id(self) -> str:
        """Return the zone ID."""
        return self._zone_id
