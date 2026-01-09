"""Device helpers for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import UFHControllerDataUpdateCoordinator


def get_controller_device_info(
    coordinator: UFHControllerDataUpdateCoordinator,
) -> DeviceInfo:
    """Get device info for the main controller device."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name=coordinator.config_entry.data.get("name", "UFH Controller"),
        manufacturer="UFH Controller",
        model="Heating Controller",
        sw_version="0.1.0",
    )


def get_zone_device_info(
    coordinator: UFHControllerDataUpdateCoordinator,
    zone_id: str,
    zone_name: str,
) -> DeviceInfo:
    """Get device info for a zone device linked to a subentry."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_{zone_id}")},
        name=zone_name,
        manufacturer="UFH Controller",
        model="Heating Zone",
        via_device=(DOMAIN, coordinator.config_entry.entry_id),
    )
