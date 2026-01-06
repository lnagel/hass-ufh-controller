"""Switch platform for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

from .const import SUBENTRY_TYPE_CONTROLLER
from .entity import UFHControllerEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


def _get_controller_subentry_id(entry: UFHControllerConfigEntry) -> str | None:
    """Get the controller subentry ID."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            return subentry.subentry_id
    return None


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator = entry.runtime_data.coordinator
    controller_subentry_id = _get_controller_subentry_id(entry)

    if controller_subentry_id is None:
        return

    async_add_entities(
        [
            UFHHeatRequestSwitch(coordinator, controller_subentry_id),
            UFHFlushEnabledSwitch(coordinator, controller_subentry_id),
        ],
        config_subentry_id=controller_subentry_id,
    )


class UFHHeatRequestSwitch(UFHControllerEntity, SwitchEntity):
    """Switch entity showing aggregated heat request status (read-only)."""

    _attr_translation_key = "heat_request"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator, subentry_id)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_heat_request"

    @property
    def is_on(self) -> bool:
        """Return the heat request status."""
        return self.coordinator.data.get("heat_request", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on is not supported (read-only switch)."""
        # Heat request is calculated, not directly controllable

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off is not supported (read-only switch)."""
        # Heat request is calculated, not directly controllable


class UFHFlushEnabledSwitch(UFHControllerEntity, SwitchEntity):
    """Switch entity for DHW latent heat capture (flush) enable."""

    _attr_translation_key = "flush_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH

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
        self.coordinator.controller.state.flush_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable DHW latent heat capture."""
        self.coordinator.controller.state.flush_enabled = False
        self.async_write_ha_state()
