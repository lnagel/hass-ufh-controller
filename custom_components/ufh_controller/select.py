"""Select platform for Underfloor Heating Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.select import SelectEntity

from .const import OperationMode
from .entity import UFHControllerEntity, get_controller_subentry_id

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator = entry.runtime_data.coordinator
    controller_subentry_id = get_controller_subentry_id(entry)

    if controller_subentry_id is None:
        return

    async_add_entities(
        [UFHModeSelect(coordinator, controller_subentry_id)],
        config_subentry_id=controller_subentry_id,
    )


class UFHModeSelect(UFHControllerEntity, SelectEntity):
    """Select entity for controller operation mode."""

    _attr_translation_key = "mode"
    _attr_options: ClassVar[list[str]] = [mode.value for mode in OperationMode]
    _attr_entity_registry_visible_default = False

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, subentry_id)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_mode"

    @property
    def current_option(self) -> str:
        """Return the current mode."""
        return self.coordinator.data.get("mode", OperationMode.HEAT)

    async def async_select_option(self, option: str) -> None:
        """Set the operation mode."""
        await self.coordinator.set_mode(option)
