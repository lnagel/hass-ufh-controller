"""
Custom integration to integrate UFH Controller with Home Assistant.

For more details about this integration, please refer to
https://github.com/lnagel/hass-ufh-controller
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_TIMING,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
)
from .coordinator import UFHControllerDataUpdateCoordinator
from .data import UFHControllerData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr

    from .data import UFHControllerConfigEntry

CONTROLLER_SUBENTRY_UNIQUE_ID = "controller"

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> bool:
    """Set up UFH Controller from a config entry."""
    LOGGER.debug("Setting up UFH Controller entry: %s", entry.entry_id)

    # Ensure controller subentry exists (auto-create if missing)
    await _async_ensure_controller_subentry(hass, entry)

    coordinator = UFHControllerDataUpdateCoordinator(hass=hass, entry=entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = UFHControllerData(coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Listen for subentry updates and reload when zone subentries change
    async def _async_handle_subentry_update(event: Any) -> None:
        """Handle subentry update event."""
        if event.data.get("entry_id") != entry.entry_id:
            return
        subentry_type = event.data.get("subentry_type")
        if subentry_type == SUBENTRY_TYPE_ZONE:
            LOGGER.debug("Zone subentry updated, scheduling reload")
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen("config_subentry_updated", _async_handle_subentry_update)
    )

    return True


async def _async_ensure_controller_subentry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> None:
    """Ensure the controller subentry exists, creating it if needed."""
    # Check if controller subentry already exists
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            LOGGER.debug("Controller subentry already exists: %s", subentry.subentry_id)
            return

    # Create controller subentry with timing data
    # Try to migrate timing from options if available, otherwise use defaults
    timing = entry.options.get("timing", DEFAULT_TIMING)
    controller_name = entry.data.get("name", "UFH Controller")
    controller_subentry = ConfigSubentry(
        data=MappingProxyType({"timing": timing}),
        subentry_type=SUBENTRY_TYPE_CONTROLLER,
        title=controller_name,
        unique_id=CONTROLLER_SUBENTRY_UNIQUE_ID,
    )

    hass.config_entries.async_add_subentry(entry, controller_subentry)
    LOGGER.debug("Created controller subentry for: %s", controller_name)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    LOGGER.debug("Unloading UFH Controller entry: %s", entry.entry_id)

    # Save state before unloading
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_save_state()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Handle device removal request."""
    LOGGER.debug(
        "async_remove_config_entry_device called for device: %s, identifiers: %s",
        device_entry.id,
        device_entry.identifiers,
    )

    # Find the device identifier for our domain
    device_id = None
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            device_id = identifier[1]
            break

    if device_id is None:
        LOGGER.debug("No identifier found for domain %s", DOMAIN)
        return False

    # The controller device has identifier = entry_id
    # Zone devices have identifier = entry_id + "_" + zone_id
    if device_id == entry.entry_id:
        # Cannot delete the main controller device
        LOGGER.debug("Cannot delete main controller device")
        msg = "Cannot delete the controller. To remove it, delete the integration."
        raise HomeAssistantError(msg)

    # Zone devices are managed through subentries - deletion is handled by HA
    # when the subentry is deleted. Allow orphan device cleanup.
    LOGGER.debug("Allowing device removal for: %s", device_id)
    return True


__all__ = [
    "DOMAIN",
    "async_setup_entry",
    "async_unload_entry",
]
