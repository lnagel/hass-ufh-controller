"""Select platform for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .const import OperationMode
from .entity import UFHControllerEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities([UFHModeSelect(coordinator)])


class UFHModeSelect(UFHControllerEntity, SelectEntity):
    """Select entity for controller operation mode."""

    _attr_translation_key = "mode"
    _attr_options = [mode.value for mode in OperationMode]

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_mode"

    @property
    def current_option(self) -> str:
        """Return the current mode."""
        return self.coordinator.data.get("mode", OperationMode.AUTO)

    async def async_select_option(self, option: str) -> None:
        """Set the operation mode."""
        self.coordinator.set_mode(option)
