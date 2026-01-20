"""Switch platform for Underfloor Heating Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

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
    """Set up the switch platform."""
    coordinator = entry.runtime_data.coordinator
    controller_subentry_id = get_controller_subentry_id(entry)

    if controller_subentry_id is None:
        return

    # Only create flush switch if DHW entity is configured
    # (flush feature requires DHW state to function)
    if entry.data.get("dhw_active_entity"):
        async_add_entities(
            [
                UFHFlushEnabledSwitch(coordinator, controller_subentry_id),
            ],
            config_subentry_id=controller_subentry_id,
        )


class UFHFlushEnabledSwitch(UFHControllerEntity, SwitchEntity):
    """Switch entity for DHW latent heat capture (flush) enable."""

    _attr_translation_key = "flush_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_registry_visible_default = False

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator, subentry_id)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_flush_enabled"

    @property
    def is_on(self) -> bool:
        """Return the flush enabled status."""
        return self.coordinator.controller.state.flush_enabled

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable DHW latent heat capture."""
        await self.coordinator.set_flush_enabled(enabled=True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable DHW latent heat capture."""
        await self.coordinator.set_flush_enabled(enabled=False)
