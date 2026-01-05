"""Custom types for ufh_controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import UFHControllerApiClient
    from .coordinator import UFHControllerDataUpdateCoordinator


type UFHControllerConfigEntry = ConfigEntry[UFHControllerData]


@dataclass
class UFHControllerData:
    """Data for the UFH Controller integration."""

    client: UFHControllerApiClient
    coordinator: UFHControllerDataUpdateCoordinator
    integration: Integration
