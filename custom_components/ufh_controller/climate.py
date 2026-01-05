"""Climate platform for UFH Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)

from .const import DEFAULT_SETPOINT, DOMAIN
from .entity import UFHControllerZoneEntity

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
    """Set up the climate platform."""
    coordinator = entry.runtime_data.coordinator

    # Create a climate entity for each zone
    entities: list[UFHZoneClimate] = []
    for zone_config in entry.options.get("zones", []):
        entities.append(
            UFHZoneClimate(
                coordinator=coordinator,
                zone_id=zone_config["id"],
                zone_name=zone_config["name"],
                zone_config=zone_config,
            )
        )

    async_add_entities(entities)


class UFHZoneClimate(UFHControllerZoneEntity, ClimateEntity):
    """Climate entity for a UFH zone."""

    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_temperature_unit = "°C"
    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        zone_config: dict[str, Any],
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, zone_id, zone_name)

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{zone_id}_climate"
        self._attr_translation_key = "zone"

        # Temperature settings
        setpoint_config = zone_config.get("setpoint", DEFAULT_SETPOINT)
        self._attr_min_temp = setpoint_config.get("min", DEFAULT_SETPOINT["min"])
        self._attr_max_temp = setpoint_config.get("max", DEFAULT_SETPOINT["max"])
        self._attr_target_temperature_step = setpoint_config.get(
            "step", DEFAULT_SETPOINT["step"]
        )

        # Supported features
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        # Presets
        presets = zone_config.get("presets", {})
        if presets:
            features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = list(presets.keys())
            self._presets = presets
        else:
            self._attr_preset_modes = None
            self._presets = {}

        self._attr_supported_features = features
        self._attr_preset_mode: str | None = None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        if zone_data.get("enabled", True):
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current HVAC action."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})

        if not zone_data.get("enabled", True):
            return HVACAction.OFF

        if zone_data.get("valve_on", False):
            return HVACAction.HEATING

        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return zone_data.get("current_temp")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return zone_data.get("setpoint")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (temperature := kwargs.get("temperature")) is not None:
            self.coordinator.set_zone_setpoint(self._zone_id, temperature)
            # Clear preset when manually setting temperature
            self._attr_preset_mode = None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if hvac_mode == HVACMode.HEAT:
            self.coordinator.set_zone_enabled(self._zone_id, enabled=True)
        elif hvac_mode == HVACMode.OFF:
            self.coordinator.set_zone_enabled(self._zone_id, enabled=False)

    async def async_turn_on(self) -> None:
        """Turn the zone on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the zone off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        if preset_mode not in self._presets:
            return

        preset = self._presets[preset_mode]
        if "setpoint" in preset:
            self.coordinator.set_zone_setpoint(self._zone_id, preset["setpoint"])

        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return {
            "duty_cycle": zone_data.get("duty_cycle"),
            "pid_error": zone_data.get("error"),
            "integral": zone_data.get("integral"),
            "window_blocked": zone_data.get("window_blocked", False),
            "is_requesting_heat": zone_data.get("is_requesting_heat", False),
        }
