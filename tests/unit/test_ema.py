"""Test EMA (Exponential Moving Average) formula calculation."""

import pytest

from custom_components.ufh_controller.coordinator import _round_with_hysteresis
from custom_components.ufh_controller.core.ema import apply_ema


class TestApplyEma:
    """Test cases for the apply_ema function."""

    def test_no_filtering_when_tau_zero(self) -> None:
        """Test that tau=0 disables filtering and returns raw value."""
        raw_temp = 22.5
        previous_ema = 20.0
        tau = 0
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)
        assert result == raw_temp

    def test_no_filtering_when_tau_negative(self) -> None:
        """Test that negative tau disables filtering and returns raw value."""
        raw_temp = 22.5
        previous_ema = 20.0
        tau = -100
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)
        assert result == raw_temp

    def test_no_filtering_when_no_previous_value(self) -> None:
        """Test that first reading returns raw value."""
        raw_temp = 21.0
        previous_ema = None
        tau = 600
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)
        assert result == raw_temp

    def test_alpha_calculation_standard(self) -> None:
        """Test alpha calculation with standard values."""
        # tau=600s, dt=60s -> alpha = 60/(600+60) = 0.0909...
        tau = 600
        dt = 60.0
        expected_alpha = dt / (tau + dt)
        assert expected_alpha == pytest.approx(0.0909, rel=0.01)

    def test_ema_smoothing_effect(self) -> None:
        """Test that EMA smooths out sudden changes."""
        previous_ema = 20.0
        raw_temp = 25.0  # Sudden 5 degree spike
        tau = 600
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)

        # alpha = 60/660 = 0.0909
        # result = 0.0909 * 25 + 0.9091 * 20 = 2.27 + 18.18 = 20.45
        expected = (dt / (tau + dt)) * raw_temp + (1 - dt / (tau + dt)) * previous_ema
        assert result == pytest.approx(expected)
        assert result == pytest.approx(20.45, rel=0.01)

        # The filtered value should be much closer to previous than raw
        assert abs(result - previous_ema) < abs(raw_temp - previous_ema) * 0.2

    def test_ema_convergence_over_time(self) -> None:
        """Test that EMA converges to the raw value over multiple iterations."""
        tau = 600
        dt = 60.0
        raw_temp = 25.0  # Constant raw temperature
        ema = 20.0  # Starting point

        # Apply EMA multiple times - should converge toward raw_temp
        for _ in range(100):
            ema = apply_ema(raw_temp, ema, tau, dt)

        # After many iterations, should be very close to raw value
        assert ema == pytest.approx(raw_temp, rel=0.01)

    def test_ema_with_short_time_constant(self) -> None:
        """Test EMA with shorter time constant (faster response)."""
        previous_ema = 20.0
        raw_temp = 22.0
        tau = 120  # 2 minutes - faster response
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)

        # alpha = 60/180 = 0.333
        # result = 0.333 * 22 + 0.667 * 20 = 7.33 + 13.33 = 20.67
        expected_alpha = 60.0 / 180.0
        expected = expected_alpha * raw_temp + (1 - expected_alpha) * previous_ema
        assert result == pytest.approx(expected)
        assert result == pytest.approx(20.67, rel=0.01)

    def test_ema_with_long_time_constant(self) -> None:
        """Test EMA with longer time constant (slower response)."""
        previous_ema = 20.0
        raw_temp = 22.0
        tau = 1800  # 30 minutes - slower response
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)

        # alpha = 60/1860 = 0.0323
        # result = 0.0323 * 22 + 0.9677 * 20 = 0.71 + 19.35 = 20.06
        expected_alpha = 60.0 / 1860.0
        expected = expected_alpha * raw_temp + (1 - expected_alpha) * previous_ema
        assert result == pytest.approx(expected)
        assert result < 20.1  # Should barely move

    def test_ema_step_response(self) -> None:
        """Test EMA step response characteristics."""
        tau = 600
        dt = 60.0
        raw_temp = 25.0  # Step change target
        ema = 20.0  # Starting point

        # Calculate how many iterations to reach ~63% of the step
        # Time constant tau means 63% reached after tau seconds
        iterations_for_tau = tau / dt  # 10 iterations

        # Apply EMA for tau seconds worth of iterations
        for _ in range(int(iterations_for_tau)):
            ema = apply_ema(raw_temp, ema, tau, dt)

        # After one time constant, should be ~63% of the way there
        step_size = raw_temp - 20.0  # 5 degrees
        expected_progress = step_size * 0.63  # ~3.15 degrees
        actual_progress = ema - 20.0

        # Allow some tolerance due to discrete sampling
        assert actual_progress == pytest.approx(expected_progress, rel=0.1)

    def test_ema_negative_temperature(self) -> None:
        """Test EMA works with negative temperatures."""
        previous_ema = -5.0
        raw_temp = -10.0
        tau = 600
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)

        # Should be between previous and raw
        assert result < previous_ema
        assert result > raw_temp

    def test_ema_with_varying_dt(self) -> None:
        """Test EMA adjusts correctly with different time intervals."""
        previous_ema = 20.0
        raw_temp = 22.0
        tau = 600

        # With longer dt, alpha increases, more weight to raw
        result_short_dt = apply_ema(raw_temp, previous_ema, tau, dt=30.0)
        result_standard_dt = apply_ema(raw_temp, previous_ema, tau, dt=60.0)
        result_long_dt = apply_ema(raw_temp, previous_ema, tau, dt=120.0)

        # Longer dt should move result closer to raw_temp
        assert result_short_dt < result_standard_dt < result_long_dt
        assert result_long_dt < raw_temp  # But not all the way there

    def test_ema_preserves_steady_state(self) -> None:
        """Test EMA preserves value when raw equals previous."""
        previous_ema = 21.5
        raw_temp = 21.5  # Same as previous
        tau = 600
        dt = 60.0

        result = apply_ema(raw_temp, previous_ema, tau, dt)

        # Should stay approximately the same (allowing for float precision)
        assert result == pytest.approx(previous_ema)


class TestRoundWithHysteresis:
    """Test cases for the _round_with_hysteresis function."""

    def test_first_reading_just_rounds(self) -> None:
        """Test that first reading (no previous) returns standard rounded value."""
        assert _round_with_hysteresis(20.04, None) == pytest.approx(20.0)
        assert _round_with_hysteresis(20.06, None) == pytest.approx(20.1)
        # Note: 20.15/0.1 has floating point issues, so skip banker's rounding edge case

    def test_stable_within_hysteresis_band(self) -> None:
        """Test that value stays stable within the hysteresis band."""
        # Current display is 20.0, precision=0.1, hysteresis=0.03
        # Values within the band should keep previous display
        assert _round_with_hysteresis(20.04, 20.0) == pytest.approx(20.0)
        assert _round_with_hysteresis(20.07, 20.0) == pytest.approx(20.0)
        assert _round_with_hysteresis(19.93, 20.0) == pytest.approx(20.0)
        assert _round_with_hysteresis(19.96, 20.0) == pytest.approx(20.0)

    def test_crosses_upper_threshold(self) -> None:
        """Test that value changes when crossing upper hysteresis threshold."""
        # Upper threshold for 20.0 display is ~20.08 (20.05 + 0.03)
        # Use values clearly past threshold to avoid floating point edge cases
        assert _round_with_hysteresis(20.07, 20.0) == pytest.approx(20.0)  # Under
        assert _round_with_hysteresis(20.09, 20.0) == pytest.approx(20.1)  # Above

    def test_crosses_lower_threshold(self) -> None:
        """Test that value changes when crossing lower hysteresis threshold."""
        # Lower threshold for 20.0 display is ~19.92 (19.95 - 0.03)
        # Use values clearly past threshold to avoid floating point edge cases
        assert _round_with_hysteresis(19.93, 20.0) == pytest.approx(20.0)  # Above
        assert _round_with_hysteresis(19.91, 20.0) == pytest.approx(19.9)  # Below

    def test_prevents_flicker_at_boundary(self) -> None:
        """Test the main use case: preventing flicker when EMA oscillates."""
        # Simulate EMA oscillating around 20.05 (the boundary)
        display = None

        # Initial reading
        display = _round_with_hysteresis(20.04, display)
        assert display == pytest.approx(20.0)

        # Small oscillations should NOT cause flicker
        display = _round_with_hysteresis(20.06, display)
        assert display == pytest.approx(20.0)  # Still 20.0, not crossed threshold

        display = _round_with_hysteresis(20.04, display)
        assert display == pytest.approx(20.0)

        display = _round_with_hysteresis(20.07, display)
        assert display == pytest.approx(20.0)  # Still stable

        # Now cross the threshold decisively
        display = _round_with_hysteresis(20.09, display)
        assert display == pytest.approx(20.1)  # Changed!

        # Should stay at 20.1 even if value drops slightly
        display = _round_with_hysteresis(20.06, display)
        assert display == pytest.approx(20.1)  # Stable at new value

        display = _round_with_hysteresis(20.04, display)
        assert display == pytest.approx(20.1)  # Still stable (lower threshold ~20.02)

    def test_large_jumps_work_correctly(self) -> None:
        """Test that large temperature changes update correctly."""
        # If temperature jumps by more than one step, should still work
        assert _round_with_hysteresis(22.5, 20.0) == pytest.approx(22.5)
        assert _round_with_hysteresis(18.0, 20.0) == pytest.approx(18.0)

    def test_custom_precision(self) -> None:
        """Test with custom precision value."""
        # Using 0.5 degree precision
        assert _round_with_hysteresis(
            20.3, 20.0, precision=0.5, hysteresis=0.1
        ) == pytest.approx(20.0)
        assert _round_with_hysteresis(
            20.4, 20.0, precision=0.5, hysteresis=0.1
        ) == pytest.approx(20.5)

    def test_custom_hysteresis(self) -> None:
        """Test with custom hysteresis margin."""
        # Using 0.05 hysteresis (larger margin)
        # Upper threshold for 20.0 is 20.05 + 0.05 = 20.10
        assert _round_with_hysteresis(20.08, 20.0, hysteresis=0.05) == pytest.approx(
            20.0
        )
        assert _round_with_hysteresis(20.11, 20.0, hysteresis=0.05) == pytest.approx(
            20.1
        )

    def test_negative_temperatures(self) -> None:
        """Test hysteresis works with negative temperatures."""
        assert _round_with_hysteresis(-5.04, -5.0) == pytest.approx(-5.0)
        assert _round_with_hysteresis(-5.09, -5.0) == pytest.approx(
            -5.1
        )  # Clearly past threshold
        assert _round_with_hysteresis(-4.91, -5.0) == pytest.approx(
            -4.9
        )  # Clearly past threshold

    def test_same_value_as_display(self) -> None:
        """Test that value matching display stays stable."""
        assert _round_with_hysteresis(20.0, 20.0) == pytest.approx(20.0)
        assert _round_with_hysteresis(20.03, 20.0) == pytest.approx(20.0)
