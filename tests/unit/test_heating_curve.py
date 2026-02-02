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


class TestHeatingCurveCalculation:
    """Test heating curve calculation logic."""

    @pytest.fixture
    def default_config(self) -> HeatingCurveConfig:
        """Create a default heating curve config."""
        return HeatingCurveConfig(
            outdoor_temp_warm=DEFAULT_OUTDOOR_TEMP_WARM,  # 15°C
            outdoor_temp_cold=DEFAULT_OUTDOOR_TEMP_COLD,  # -10°C
            supply_temp_warm=DEFAULT_SUPPLY_TEMP_WARM,  # 25°C
            supply_temp_cold=DEFAULT_SUPPLY_TEMP_COLD,  # 45°C
            supply_target_temp=DEFAULT_SUPPLY_TARGET_TEMP,  # 40°C fallback
        )

    def test_outdoor_temp_unavailable_uses_fallback(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """When outdoor temp is None, uses supply_target_temp fallback."""
        result = calculate_supply_target(default_config, None)
        assert result == DEFAULT_SUPPLY_TARGET_TEMP

    def test_outdoor_at_warm_point_returns_supply_warm(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Outdoor at warm design point returns supply_temp_warm."""
        result = calculate_supply_target(default_config, 15.0)
        assert result == DEFAULT_SUPPLY_TEMP_WARM  # 25°C

    def test_outdoor_at_cold_point_returns_supply_cold(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Outdoor at cold design point returns supply_temp_cold."""
        result = calculate_supply_target(default_config, -10.0)
        assert result == DEFAULT_SUPPLY_TEMP_COLD  # 45°C

    def test_outdoor_above_warm_point_clamps_to_supply_warm(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Outdoor above warm point clamps to supply_temp_warm."""
        result = calculate_supply_target(default_config, 25.0)
        assert result == DEFAULT_SUPPLY_TEMP_WARM  # 25°C

    def test_outdoor_below_cold_point_clamps_to_supply_cold(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Outdoor below cold point clamps to supply_temp_cold."""
        result = calculate_supply_target(default_config, -20.0)
        assert result == DEFAULT_SUPPLY_TEMP_COLD  # 45°C

    def test_linear_interpolation_at_midpoint(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Midpoint outdoor temp (2.5°C) returns midpoint supply target (35°C)."""
        # Midpoint of [-10, 15] is 2.5
        # Midpoint of [25, 45] is 35
        result = calculate_supply_target(default_config, 2.5)
        assert result == pytest.approx(35.0)

    def test_linear_interpolation_at_quarter_point(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Quarter point calculation validates linear interpolation."""
        # At outdoor 8.75°C (25% from warm to cold), supply should be 30°C
        # (15 - 8.75) / (15 - (-10)) = 6.25 / 25 = 0.25
        # 25 + (45 - 25) * 0.25 = 25 + 5 = 30
        result = calculate_supply_target(default_config, 8.75)
        assert result == pytest.approx(30.0)

    def test_linear_interpolation_at_three_quarter_point(
        self, default_config: HeatingCurveConfig
    ) -> None:
        """Three-quarter point calculation validates linear interpolation."""
        # At outdoor -3.75°C (75% from warm to cold), supply should be 40°C
        # (15 - (-3.75)) / (15 - (-10)) = 18.75 / 25 = 0.75
        # 25 + (45 - 25) * 0.75 = 25 + 15 = 40
        result = calculate_supply_target(default_config, -3.75)
        assert result == pytest.approx(40.0)

    def test_invalid_curve_warm_equals_cold_uses_fallback(self) -> None:
        """Invalid curve (warm == cold outdoor temps) uses fallback."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=10.0,
            outdoor_temp_cold=10.0,  # Same as warm - invalid
            supply_temp_warm=25.0,
            supply_temp_cold=45.0,
            supply_target_temp=40.0,
        )
        result = calculate_supply_target(config, 5.0)
        assert result == 40.0  # Fallback

    def test_invalid_curve_warm_less_than_cold_uses_fallback(self) -> None:
        """Invalid curve (warm < cold outdoor temps) uses fallback."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=-5.0,
            outdoor_temp_cold=10.0,  # Greater than warm - invalid
            supply_temp_warm=25.0,
            supply_temp_cold=45.0,
            supply_target_temp=40.0,
        )
        result = calculate_supply_target(config, 5.0)
        assert result == 40.0  # Fallback

    def test_custom_curve_parameters(self) -> None:
        """Test with custom heating curve parameters."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=20.0,
            outdoor_temp_cold=-15.0,
            supply_temp_warm=30.0,
            supply_temp_cold=50.0,
            supply_target_temp=45.0,
        )
        # At outdoor 2.5°C (50% from warm to cold):
        # (20 - 2.5) / (20 - (-15)) = 17.5 / 35 = 0.5
        # 30 + (50 - 30) * 0.5 = 30 + 10 = 40
        result = calculate_supply_target(config, 2.5)
        assert result == pytest.approx(40.0)


class TestHeatingCurveEdgeCases:
    """Test edge cases for heating curve calculation."""

    def test_zero_outdoor_temp(self) -> None:
        """Test calculation at 0°C outdoor temperature."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=15.0,
            outdoor_temp_cold=-10.0,
            supply_temp_warm=25.0,
            supply_temp_cold=45.0,
            supply_target_temp=40.0,
        )
        # At 0°C: (15 - 0) / (15 - (-10)) = 15/25 = 0.6
        # 25 + (45 - 25) * 0.6 = 25 + 12 = 37
        result = calculate_supply_target(config, 0.0)
        assert result == pytest.approx(37.0)

    def test_negative_supply_range(self) -> None:
        """Test with supply_warm > supply_cold (unusual but valid config)."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=15.0,
            outdoor_temp_cold=-10.0,
            supply_temp_warm=45.0,  # Higher at warm point
            supply_temp_cold=25.0,  # Lower at cold point
            supply_target_temp=35.0,
        )
        # Clamping: max(warm, min(cold, value)) = max(45, min(25, calc)) = 45
        # since 45 > 25, it always returns 45 (the warm value)
        result = calculate_supply_target(config, 15.0)
        assert result == 45.0

    def test_extreme_outdoor_temps(self) -> None:
        """Test with extreme outdoor temperatures."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=15.0,
            outdoor_temp_cold=-10.0,
            supply_temp_warm=25.0,
            supply_temp_cold=45.0,
            supply_target_temp=40.0,
        )
        # Very cold (-40°C) should clamp to supply_cold
        result_cold = calculate_supply_target(config, -40.0)
        assert result_cold == 45.0

        # Very warm (40°C) should clamp to supply_warm
        result_warm = calculate_supply_target(config, 40.0)
        assert result_warm == 25.0

    def test_small_temperature_differences(self) -> None:
        """Test with very small temperature ranges."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=5.0,
            outdoor_temp_cold=4.0,  # Only 1°C range
            supply_temp_warm=30.0,
            supply_temp_cold=35.0,  # Only 5°C range
            supply_target_temp=32.0,
        )
        # At 4.5°C (midpoint): should return 32.5°C
        result = calculate_supply_target(config, 4.5)
        assert result == pytest.approx(32.5)


class TestHeatingCurveNoEntity:
    """Test heating curve when no outdoor entity is configured."""

    def test_no_outdoor_entity_always_returns_fallback(self) -> None:
        """When outdoor temp is None, always use fallback."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=15.0,
            outdoor_temp_cold=-10.0,
            supply_temp_warm=25.0,
            supply_temp_cold=45.0,
            supply_target_temp=40.0,
        )
        # When coordinator has no outdoor entity configured,
        # it will pass None for outdoor temp.
        # Testing that None outdoor temp gives fallback.
        result = calculate_supply_target(config, None)
        assert result == 40.0  # Fallback


class TestHeatingCurveConfigValidation:
    """Test HeatingCurveConfig validation."""

    def test_valid_config(self) -> None:
        """Test that valid config is recognized."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=15.0,
            outdoor_temp_cold=-10.0,
        )
        assert config.is_valid() is True

    def test_invalid_config_equal_temps(self) -> None:
        """Test that equal outdoor temps is invalid."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=10.0,
            outdoor_temp_cold=10.0,
        )
        assert config.is_valid() is False

    def test_invalid_config_warm_less_than_cold(self) -> None:
        """Test that warm < cold is invalid."""
        config = HeatingCurveConfig(
            outdoor_temp_warm=-5.0,
            outdoor_temp_cold=10.0,
        )
        assert config.is_valid() is False
