"""
Custom integration to integrate UFH Controller with Home Assistant.

For more details about this integration, please refer to
https://github.com/lnagel/hass-ufh-controller
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .const import DOMAIN, LOGGER
from .coordinator import UFHControllerDataUpdateCoordinator
from .data import UFHControllerData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import UFHControllerConfigEntry

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

    coordinator = UFHControllerDataUpdateCoordinator(hass=hass, entry=entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = UFHControllerData(coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    LOGGER.debug("Unloading UFH Controller entry: %s", entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


__all__ = [
    "DOMAIN",
    "async_setup_entry",
    "async_unload_entry",
]
