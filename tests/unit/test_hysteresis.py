"""Test hysteresis rounding for temperature display."""

import pytest

from custom_components.ufh_controller.core.hysteresis import round_with_hysteresis


class TestRoundWithHysteresis:
    """Test cases for the round_with_hysteresis function."""

    def test_first_reading_just_rounds(self) -> None:
        """Test that first reading (no previous) returns standard rounded value."""
        assert round_with_hysteresis(20.04, None) == pytest.approx(20.0)
        assert round_with_hysteresis(20.06, None) == pytest.approx(20.1)
        # Note: 20.15/0.1 has floating point issues, so skip banker's rounding edge case

    def test_stable_within_hysteresis_band(self) -> None:
        """Test that value stays stable within the hysteresis band."""
        # Current display is 20.0, precision=0.1, hysteresis=0.03
        # Values within the band should keep previous display
        assert round_with_hysteresis(20.04, 20.0) == pytest.approx(20.0)
        assert round_with_hysteresis(20.07, 20.0) == pytest.approx(20.0)
        assert round_with_hysteresis(19.93, 20.0) == pytest.approx(20.0)
        assert round_with_hysteresis(19.96, 20.0) == pytest.approx(20.0)

    def test_crosses_upper_threshold(self) -> None:
        """Test that value changes when crossing upper hysteresis threshold."""
        # Upper threshold for 20.0 display is ~20.08 (20.05 + 0.03)
        # Use values clearly past threshold to avoid floating point edge cases
        assert round_with_hysteresis(20.07, 20.0) == pytest.approx(20.0)  # Under
        assert round_with_hysteresis(20.09, 20.0) == pytest.approx(20.1)  # Above

    def test_crosses_lower_threshold(self) -> None:
        """Test that value changes when crossing lower hysteresis threshold."""
        # Lower threshold for 20.0 display is ~19.92 (19.95 - 0.03)
        # Use values clearly past threshold to avoid floating point edge cases
        assert round_with_hysteresis(19.93, 20.0) == pytest.approx(20.0)  # Above
        assert round_with_hysteresis(19.91, 20.0) == pytest.approx(19.9)  # Below

    def test_prevents_flicker_at_boundary(self) -> None:
        """Test the main use case: preventing flicker when EMA oscillates."""
        # Simulate EMA oscillating around 20.05 (the boundary)
        display = None

        # Initial reading
        display = round_with_hysteresis(20.04, display)
        assert display == pytest.approx(20.0)

        # Small oscillations should NOT cause flicker
        display = round_with_hysteresis(20.06, display)
        assert display == pytest.approx(20.0)  # Still 20.0, not crossed threshold

        display = round_with_hysteresis(20.04, display)
        assert display == pytest.approx(20.0)

        display = round_with_hysteresis(20.07, display)
        assert display == pytest.approx(20.0)  # Still stable

        # Now cross the threshold decisively
        display = round_with_hysteresis(20.09, display)
        assert display == pytest.approx(20.1)  # Changed!

        # Should stay at 20.1 even if value drops slightly
        display = round_with_hysteresis(20.06, display)
        assert display == pytest.approx(20.1)  # Stable at new value

        display = round_with_hysteresis(20.04, display)
        assert display == pytest.approx(20.1)  # Still stable (lower threshold ~20.02)

    def test_large_jumps_work_correctly(self) -> None:
        """Test that large temperature changes update correctly."""
        # If temperature jumps by more than one step, should still work
        assert round_with_hysteresis(22.5, 20.0) == pytest.approx(22.5)
        assert round_with_hysteresis(18.0, 20.0) == pytest.approx(18.0)

    def test_custom_precision(self) -> None:
        """Test with custom precision value."""
        # Using 0.5 degree precision
        assert round_with_hysteresis(
            20.3, 20.0, precision=0.5, hysteresis=0.1
        ) == pytest.approx(20.0)
        assert round_with_hysteresis(
            20.4, 20.0, precision=0.5, hysteresis=0.1
        ) == pytest.approx(20.5)

    def test_custom_hysteresis(self) -> None:
        """Test with custom hysteresis margin."""
        # Using 0.05 hysteresis (larger margin)
        # Upper threshold for 20.0 is 20.05 + 0.05 = 20.10
        assert round_with_hysteresis(20.08, 20.0, hysteresis=0.05) == pytest.approx(
            20.0
        )
        assert round_with_hysteresis(20.11, 20.0, hysteresis=0.05) == pytest.approx(
            20.1
        )

    def test_negative_temperatures(self) -> None:
        """Test hysteresis works with negative temperatures."""
        assert round_with_hysteresis(-5.04, -5.0) == pytest.approx(-5.0)
        assert round_with_hysteresis(-5.09, -5.0) == pytest.approx(
            -5.1
        )  # Clearly past threshold
        assert round_with_hysteresis(-4.91, -5.0) == pytest.approx(
            -4.9
        )  # Clearly past threshold

    def test_same_value_as_display(self) -> None:
        """Test that value matching display stays stable."""
        assert round_with_hysteresis(20.0, 20.0) == pytest.approx(20.0)
        assert round_with_hysteresis(20.03, 20.0) == pytest.approx(20.0)
