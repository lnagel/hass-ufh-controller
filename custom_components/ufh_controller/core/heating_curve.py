"""
Heating curve calculation for outdoor temperature compensation.

This module provides pure functions for calculating dynamic supply target
temperatures based on outdoor temperature using a two-point linear interpolation
(industry standard heating curve for underfloor heating).
"""

from __future__ import annotations

from dataclasses import dataclass

from custom_components.ufh_controller.const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_SUPPLY_TARGET_TEMP,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
)


@dataclass
class HeatingCurveConfig:
    """Configuration for the heating curve calculation."""

    supply_target_temp: float = DEFAULT_SUPPLY_TARGET_TEMP
    outdoor_temp_warm: float = DEFAULT_OUTDOOR_TEMP_WARM
    outdoor_temp_cold: float = DEFAULT_OUTDOOR_TEMP_COLD
    supply_temp_warm: float = DEFAULT_SUPPLY_TEMP_WARM
    supply_temp_cold: float = DEFAULT_SUPPLY_TEMP_COLD

    def is_valid(self) -> bool:
        """Check if the heating curve configuration is valid."""
        return self.outdoor_temp_warm > self.outdoor_temp_cold


def calculate_supply_target(
    config: HeatingCurveConfig,
    outdoor_temp: float | None,
) -> float:
    """
    Calculate dynamic supply target temperature from heating curve.

    Uses two-point linear interpolation between (outdoor_warm, supply_warm)
    and (outdoor_cold, supply_cold). Result is clamped to [supply_warm, supply_cold]
    when outdoor temp is outside the design range.

    Formula:
        supply_target = supply_warm + (supply_cold - supply_warm) *
                        (outdoor_warm - outdoor_temp) / (outdoor_warm - outdoor_cold)

    Example with defaults (outdoor: 15°C→-10°C, supply: 25°C→45°C):
        - Outdoor 15°C → Supply target 25°C
        - Outdoor 2.5°C → Supply target 35°C (midpoint)
        - Outdoor -10°C → Supply target 45°C

    Args:
        config: Heating curve configuration parameters.
        outdoor_temp: Current outdoor temperature, or None if unavailable.

    Returns:
        The target supply temperature. Falls back to supply_target_temp
        if outdoor temp is unavailable or heating curve is invalid.

    """
    # Fall back to fixed target if no outdoor temp available
    if outdoor_temp is None:
        return config.supply_target_temp

    # Validate heating curve configuration (outdoor_warm must be > outdoor_cold)
    if not config.is_valid():
        return config.supply_target_temp

    # Two-point linear interpolation
    outdoor_range = config.outdoor_temp_warm - config.outdoor_temp_cold
    supply_range = config.supply_temp_cold - config.supply_temp_warm
    normalized_outdoor = (config.outdoor_temp_warm - outdoor_temp) / outdoor_range
    supply_target = config.supply_temp_warm + supply_range * normalized_outdoor

    # Clamp to design range [supply_warm, supply_cold]
    return max(config.supply_temp_warm, min(config.supply_temp_cold, supply_target))
