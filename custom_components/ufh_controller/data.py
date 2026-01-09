"""Custom types for Underfloor Heating Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import UFHControllerDataUpdateCoordinator


type UFHControllerConfigEntry = ConfigEntry[UFHControllerData]


@dataclass
class UFHControllerData:
    """Data for the Underfloor Heating Controller integration."""

    coordinator: UFHControllerDataUpdateCoordinator
