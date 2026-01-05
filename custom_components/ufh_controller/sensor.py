"""Sensor platform for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import UFHControllerConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up the sensor platform.

    Sensors will be implemented in Phase 10.
    """
