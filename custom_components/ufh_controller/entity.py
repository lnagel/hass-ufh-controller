"""Base entity classes for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import SUBENTRY_TYPE_CONTROLLER
from .coordinator import UFHControllerDataUpdateCoordinator
from .device import get_controller_device_info, get_zone_device_info

if TYPE_CHECKING:
    from .data import UFHControllerConfigEntry


def get_controller_subentry_id(entry: UFHControllerConfigEntry) -> str | None:
    """Get the controller subentry ID."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            return subentry.subentry_id
    return None


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
