"""Switch platform for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

from .entity import UFHControllerEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator = entry.runtime_data.coordinator

    entities: list[SwitchEntity] = [
        UFHHeatRequestSwitch(coordinator),
        UFHFlushEnabledSwitch(coordinator),
    ]

    async_add_entities(entities)


class UFHHeatRequestSwitch(UFHControllerEntity, SwitchEntity):
    """Switch entity showing aggregated heat request status (read-only)."""

    _attr_translation_key = "heat_request"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)

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
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)

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
