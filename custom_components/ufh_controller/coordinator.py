"""DataUpdateCoordinator for UFH Controller."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONTROLLER_LOOP_INTERVAL, DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import UFHControllerConfigEntry


class UFHControllerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching UFH Controller data."""

    config_entry: UFHControllerConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: UFHControllerConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=CONTROLLER_LOOP_INTERVAL),
        )
        self.config_entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Update data via controller logic.

        This method will be implemented in Phase 7 when the controller
        is wired into the coordinator.
        """
        # Stub: return empty state until controller is implemented
        return {}
