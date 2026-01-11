"""Test PID controller."""

import pytest

from custom_components.ufh_controller.core.pid import (
    PIDController,
    PIDState,
)


class TestPIDController:
    """Test cases for PIDController."""

    def test_proportional_response(self) -> None:
        """Test that proportional term responds to error."""
        pid = PIDController(kp=50.0, ki=0.0, kd=0.0)

        # Positive error (setpoint > current) should give positive output
        result = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert result.duty_cycle == 100.0  # 50 * 2 = 100, clamped
        assert result.p_term == 100.0

        pid.reset()

        # Smaller error
        result = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert result.duty_cycle == 50.0  # 50 * 1 = 50
        assert result.p_term == 50.0

        pid.reset()

        # Negative error (setpoint < current) should give 0 (clamped)
        result = pid.update(setpoint=20.0, current=22.0, dt=60.0)
        assert result.duty_cycle == 0.0  # 50 * -2 = -100, clamped to 0
        assert result.p_term == -100.0

    def test_integral_accumulation(self) -> None:
        """Test that integral term accumulates with dt multiplier."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0, integral_max=10000.0)

        # First update: integral = ki * error * dt = 1.0 * 1 * 60 = 60%
        result1 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state is not None
        assert pid.state.i_term == 60.0
        assert result1.duty_cycle == pytest.approx(60.0)
        assert result1.i_term == pytest.approx(60.0)

        # Second update: integral = 60 + 60 = 120%
        result2 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state.i_term == 120.0
        assert result2.duty_cycle == pytest.approx(100.0)  # Clamped to 100%

    def test_integral_anti_windup(self) -> None:
        """Test that integral is clamped to prevent windup."""
        pid = PIDController(kp=0.0, ki=0.1, kd=0.0, integral_min=0.0, integral_max=50.0)

        # Large error should clamp integral at max: 0.1 * 10 * 60 = 60, clamped to 50
        result = pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert pid.state is not None
        assert pid.state.i_term == 50.0  # Clamped at max
        assert result.duty_cycle == pytest.approx(50.0)

        # Further updates should not increase integral beyond max
        pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert pid.state.i_term == 50.0

    def test_integral_anti_windup_negative(self) -> None:
        """Test that integral is clamped at minimum too."""
        pid = PIDController(
            kp=0.0, ki=1.0, kd=0.0, integral_min=-50.0, integral_max=100.0
        )

        # Negative error should drive integral down: 1.0 * -2 * 30 = -60, clamped to -50
        pid.update(setpoint=18.0, current=20.0, dt=30.0)
        assert pid.state is not None
        assert pid.state.i_term == -50.0

    def test_output_clamped_at_zero(self) -> None:
        """Test that output is clamped at 0%."""
        pid = PIDController(kp=50.0, ki=0.0, kd=0.0)

        result = pid.update(setpoint=15.0, current=25.0, dt=60.0)
        assert result.duty_cycle == 0.0

    def test_output_clamped_at_hundred(self) -> None:
        """Test that output is clamped at 100%."""
        pid = PIDController(kp=100.0, ki=0.0, kd=0.0)

        result = pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert result.duty_cycle == 100.0

    def test_derivative_term(self) -> None:
        """Test that derivative term responds to rate of change."""
        pid = PIDController(kp=0.0, ki=0.0, kd=10.0)

        # First update sets last_error (via state.error)
        result1 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state is not None
        assert pid.state.error == 1.0  # error is stored for next derivative calc
        # d_term = 10 * (1 - 0) / 60 = 0.167
        assert result1.d_term == pytest.approx(10.0 / 60.0, rel=0.01)
        assert result1.duty_cycle == pytest.approx(10.0 / 60.0, rel=0.01)

        # Second update with same error - derivative should be 0
        result2 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert result2.d_term == pytest.approx(0.0)
        assert result2.duty_cycle == pytest.approx(0.0)

        # Third update with increasing error
        result3 = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        # d_term = 10 * (2 - 1) / 60 = 0.167
        assert result3.d_term == pytest.approx(10.0 / 60.0, rel=0.01)
        assert result3.duty_cycle == pytest.approx(10.0 / 60.0, rel=0.01)

    def test_reset(self) -> None:
        """Test that reset clears the PID state."""
        pid = PIDController(kp=50.0, ki=0.1, kd=1.0)

        pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert pid.state is not None
        assert pid.state.i_term != 0.0
        assert pid.state.error != 0.0

        pid.reset()
        assert pid.state is None

    def test_set_state(self) -> None:
        """Test that set_state sets the full PID state."""
        pid = PIDController(kp=50.0, ki=0.1, kd=0.0, integral_max=100.0)

        # Set full state directly
        state = PIDState(
            error=2.0, p_term=100.0, i_term=50.0, d_term=0.0, duty_cycle=50.0
        )
        pid.set_state(state)
        assert pid.state is not None
        assert pid.state.i_term == 50.0
        assert pid.state.error == 2.0
        assert pid.state.duty_cycle == 50.0

    def test_zero_dt(self) -> None:
        """Test that zero dt returns zero PIDState."""
        pid = PIDController(kp=50.0, ki=0.1, kd=1.0)

        result = pid.update(setpoint=22.0, current=20.0, dt=0.0)
        assert result == PIDState(
            error=0.0, p_term=0.0, i_term=0.0, d_term=0.0, duty_cycle=0.0
        )

    def test_negative_dt(self) -> None:
        """Test that negative dt returns zero PIDState."""
        pid = PIDController(kp=50.0, ki=0.1, kd=1.0)

        result = pid.update(setpoint=22.0, current=20.0, dt=-60.0)
        assert result == PIDState(
            error=0.0, p_term=0.0, i_term=0.0, d_term=0.0, duty_cycle=0.0
        )

    def test_default_values(self) -> None:
        """Test default PID parameters match spec."""
        pid = PIDController()

        assert pid.kp == 50.0
        assert pid.ki == 0.001
        assert pid.kd == 0.0
        assert pid.integral_min == 0.0
        assert pid.integral_max == 100.0

    def test_state_property_none_initially(self) -> None:
        """Test that state property is None initially."""
        pid = PIDController()
        assert pid.state is None

    def test_state_property_after_update(self) -> None:
        """Test that state property returns correct state after update."""
        pid = PIDController()
        pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert pid.state is not None
        assert isinstance(pid.state, PIDState)

    def test_combined_pid(self) -> None:
        """Test combined P, I, and D terms."""
        pid = PIDController(
            kp=10.0, ki=0.1, kd=1.0, integral_min=0.0, integral_max=1000.0
        )

        # First update
        result = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        # P = 10 * 2 = 20
        # I = ki * error * dt = 0.1 * 2 * 60 = 12% (stored in % units)
        # D = 1 * (2 - 0) / 60 = 0.033
        assert result.error == 2.0
        assert result.p_term == 20.0
        assert result.i_term == pytest.approx(12.0)
        assert result.d_term == pytest.approx(1.0 * 2.0 / 60.0)
        expected = 20.0 + 12.0 + (1.0 * 2.0 / 60.0)
        assert result.duty_cycle == pytest.approx(expected, rel=0.01)

    def test_ki_change_does_not_affect_accumulated_integral(self) -> None:
        """
        Test that changing ki doesn't alter accumulated integral contribution.

        Since integral is stored in % units (post-ki multiplication),
        modifying ki should not change the stored integral value.
        """
        pid = PIDController(kp=0.0, ki=0.01, kd=0.0, integral_max=1000.0)

        # Accumulate some integral: ki * error * dt = 0.01 * 2 * 60 = 1.2% per update
        pid.update(setpoint=22.0, current=20.0, dt=60.0)
        pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert pid.state is not None
        assert pid.state.i_term == pytest.approx(2.4)  # 1.2% + 1.2% = 2.4%

        # Store the integral before ki change
        integral_before = pid.state.i_term

        # Now change ki - this should NOT affect the stored integral
        pid.ki = 0.02

        # Integral should remain unchanged
        assert pid.state.i_term == integral_before

        # Next update uses new ki: adds ki * error * dt = 0.02 * 2 * 60 = 2.4%
        result = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert pid.state.i_term == pytest.approx(4.8)  # 2.4% + 2.4% = 4.8%
        assert result.duty_cycle == pytest.approx(4.8)  # i_term = integral = 4.8%


class TestPIDState:
    """Test cases for PIDState dataclass."""

    def test_state_is_frozen(self) -> None:
        """Test that PIDState is immutable (frozen)."""
        state = PIDState(
            error=1.0, p_term=50.0, i_term=10.0, d_term=0.0, duty_cycle=60.0
        )

        with pytest.raises(AttributeError):
            state.error = 2.0  # type: ignore[misc]

    def test_state_fields(self) -> None:
        """Test PIDState with all fields."""
        state = PIDState(
            error=2.0, p_term=100.0, i_term=30.0, d_term=0.5, duty_cycle=75.0
        )
        assert state.error == 2.0
        assert state.p_term == 100.0
        assert state.i_term == 30.0
        assert state.d_term == 0.5
        assert state.duty_cycle == 75.0

    def test_state_equality(self) -> None:
        """Test PIDState equality comparison."""
        state1 = PIDState(
            error=1.0, p_term=50.0, i_term=10.0, d_term=0.0, duty_cycle=60.0
        )
        state2 = PIDState(
            error=1.0, p_term=50.0, i_term=10.0, d_term=0.0, duty_cycle=60.0
        )
        assert state1 == state2
