"""Base entity class for UFH Controller."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UFHControllerDataUpdateCoordinator


class UFHControllerEntity(CoordinatorEntity[UFHControllerDataUpdateCoordinator]):
    """Base class for UFH Controller entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UFHControllerDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title,
            manufacturer="UFH Controller",
            model="Heating Controller",
        )
