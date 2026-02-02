"""Unit tests for heating curve calculation logic."""

import pytest

from custom_components.ufh_controller.const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_SUPPLY_TARGET_TEMP,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
)
from custom_components.ufh_controller.core.heating_curve import (
    HeatingCurveConfig,
    calculate_supply_target,
)


@pytest.fixture
def default_config() -> HeatingCurveConfig:
    """Create a default heating curve config (outdoor: 15→-10°C, supply: 25→45°C)."""
    return HeatingCurveConfig(
        outdoor_temp_warm=DEFAULT_OUTDOOR_TEMP_WARM,
        outdoor_temp_cold=DEFAULT_OUTDOOR_TEMP_COLD,
        supply_temp_warm=DEFAULT_SUPPLY_TEMP_WARM,
        supply_temp_cold=DEFAULT_SUPPLY_TEMP_COLD,
        supply_target_temp=DEFAULT_SUPPLY_TARGET_TEMP,
    )


class TestHeatingCurveCalculation:
    """Test heating curve linear interpolation and clamping."""

    @pytest.mark.parametrize(
        ("outdoor_temp", "expected_supply"),
        [
            # Design points
            (15.0, 25.0),  # Warm point
            (-10.0, 45.0),  # Cold point
            # Linear interpolation
            (2.5, 35.0),  # Midpoint
            (8.75, 30.0),  # 25% from warm to cold
            (-3.75, 40.0),  # 75% from warm to cold
            (0.0, 37.0),  # At 0°C
            # Clamping
            (25.0, 25.0),  # Above warm point → clamp to warm
            (40.0, 25.0),  # Far above warm point → clamp to warm
            (-20.0, 45.0),  # Below cold point → clamp to cold
            (-40.0, 45.0),  # Far below cold point → clamp to cold
        ],
    )
    def test_interpolation_and_clamping(
        self,
        default_config: HeatingCurveConfig,
        outdoor_temp: float,
        expected_supply: float,
    ) -> None:
        """Test linear interpolation at various outdoor temperatures."""
        result = calculate_supply_target(default_config, outdoor_temp)
        assert result == pytest.approx(expected_supply)

    def test_outdoor_temp_unavailable_uses_fallback(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """When outdoor temp is None, uses supply_target_temp fallback."""
        result = calculate_supply_target(default_config, None)
        assert result == DEFAULT_SUPPLY_TARGET_TEMP


class TestHeatingCurveCustomConfig:
    """Test heating curve with custom configuration parameters."""

    @pytest.mark.parametrize(
        ("config_kwargs", "outdoor_temp", "expected_supply"),
        [
            # Custom range: outdoor 20→-15°C, supply 30→50°C
            (
                {
                    "outdoor_temp_warm": 20.0,
                    "outdoor_temp_cold": -15.0,
                    "supply_temp_warm": 30.0,
                    "supply_temp_cold": 50.0,
                },
                2.5,  # Midpoint of 20 to -15 = 2.5
                40.0,  # Midpoint of 30 to 50 = 40
            ),
            # Very narrow outdoor range (1°C)
            (
                {
                    "outdoor_temp_warm": 5.0,
                    "outdoor_temp_cold": 4.0,
                    "supply_temp_warm": 30.0,
                    "supply_temp_cold": 35.0,
                },
                4.5,  # Midpoint
                32.5,  # Midpoint
            ),
        ],
    )
    def test_custom_parameters(
        self,
        config_kwargs: dict,
        outdoor_temp: float,
        expected_supply: float,
    ) -> None:
        """Test calculation with custom heating curve parameters."""
        config = HeatingCurveConfig(**config_kwargs, supply_target_temp=40.0)
        result = calculate_supply_target(config, outdoor_temp)
        assert result == pytest.approx(expected_supply)


class TestHeatingCurveInvalidConfig:
    """Test behavior with invalid heating curve configuration."""

    @pytest.mark.parametrize(
        ("outdoor_warm", "outdoor_cold"),
        [
            (10.0, 10.0),  # Equal temps
            (-5.0, 10.0),  # Warm < cold (inverted)
        ],
    )
    def test_invalid_curve_uses_fallback(
        self, outdoor_warm: float, outdoor_cold: float
    ) -> None:
        """Invalid curve (warm <= cold outdoor temps) uses fallback."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=outdoor_warm,
            outdoor_temp_cold=outdoor_cold,
            supply_temp_warm=25.0,
            supply_temp_cold=45.0,
            supply_target_temp=40.0,
        )
        result = calculate_supply_target(config, 5.0)
        assert result == 40.0


class TestHeatingCurveConfigValidation:
    """Test HeatingCurveConfig.is_valid() method."""

    @pytest.mark.parametrize(
        ("outdoor_warm", "outdoor_cold", "expected_valid"),
        [
            (15.0, -10.0, True),  # Valid: warm > cold
            (10.0, 10.0, False),  # Invalid: equal
            (-5.0, 10.0, False),  # Invalid: warm < cold
        ],
    )
    def test_config_validation(
        self, outdoor_warm: float, outdoor_cold: float, expected_valid: bool
    ) -> None:
        """Test that config validation correctly identifies valid/invalid configs."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=outdoor_warm,
            outdoor_temp_cold=outdoor_cold,
        )
        assert config.is_valid() is expected_valid
