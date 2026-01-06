"""Test PID controller."""

import pytest

from custom_components.ufh_controller.core.pid import PIDController, PIDState


class TestPIDController:
    """Test cases for PIDController."""

    def test_proportional_response(self) -> None:
        """Test that proportional term responds to error."""
        pid = PIDController(kp=50.0, ki=0.0, kd=0.0)

        # Positive error (setpoint > current) should give positive output
        output = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert output == 100.0  # 50 * 2 = 100

        pid.reset()

        # Smaller error
        output = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert output == 50.0  # 50 * 1 = 50

        pid.reset()

        # Negative error (setpoint < current) should give 0 (clamped)
        output = pid.update(setpoint=20.0, current=22.0, dt=60.0)
        assert output == 0.0  # 50 * -2 = -100, clamped to 0

    def test_integral_accumulation(self) -> None:
        """Test that integral term accumulates per interval (not multiplied by dt)."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0, integral_max=1000.0)

        # First update: integral = 1 (error accumulated once per interval)
        output1 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state.integral == 1.0
        assert output1 == pytest.approx(1.0)  # 1.0 * 1 = 1

        # Second update: integral = 1 + 1 = 2
        output2 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state.integral == 2.0
        assert output2 == pytest.approx(2.0)  # 1.0 * 2 = 2

    def test_integral_anti_windup(self) -> None:
        """Test that integral is clamped to prevent windup."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0, integral_min=0.0, integral_max=10.0)

        # Large error should clamp integral at max
        output = pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert pid.state.integral == 10.0  # Clamped at max (error=10, but max=10)
        assert output == pytest.approx(10.0)  # 1.0 * 10 = 10

        # Further updates should not increase integral beyond max
        pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert pid.state.integral == 10.0

    def test_integral_anti_windup_negative(self) -> None:
        """Test that integral is clamped at minimum too."""
        pid = PIDController(
            kp=0.0, ki=1.0, kd=0.0, integral_min=-1.0, integral_max=100.0
        )

        # Negative error should drive integral down: -2, clamped to -1
        pid.update(setpoint=18.0, current=20.0, dt=30.0)
        assert pid.state.integral == -1.0

    def test_output_clamped_at_zero(self) -> None:
        """Test that output is clamped at 0%."""
        pid = PIDController(kp=50.0, ki=0.0, kd=0.0)

        output = pid.update(setpoint=15.0, current=25.0, dt=60.0)
        assert output == 0.0

    def test_output_clamped_at_hundred(self) -> None:
        """Test that output is clamped at 100%."""
        pid = PIDController(kp=100.0, ki=0.0, kd=0.0)

        output = pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert output == 100.0

    def test_derivative_term(self) -> None:
        """Test that derivative term responds to rate of change."""
        pid = PIDController(kp=0.0, ki=0.0, kd=10.0)

        # First update sets last_error
        output1 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state.last_error == 1.0
        # d_term = 10 * (1 - 0) / 60 = 0.167
        assert output1 == pytest.approx(10.0 / 60.0, rel=0.01)

        # Second update with same error - derivative should be 0
        output2 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert output2 == pytest.approx(0.0)

        # Third update with increasing error
        output3 = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        # d_term = 10 * (2 - 1) / 60 = 0.167
        assert output3 == pytest.approx(10.0 / 60.0, rel=0.01)

    def test_reset(self) -> None:
        """Test that reset clears the PID state."""
        pid = PIDController(kp=50.0, ki=0.1, kd=1.0)

        pid.update(setpoint=22.0, current=20.0, dt=60.0)
        assert pid.state.integral != 0.0
        assert pid.state.last_error != 0.0

        pid.reset()
        assert pid.state.integral == 0.0
        assert pid.state.last_error == 0.0

    def test_set_integral(self) -> None:
        """Test that set_integral sets the integral value."""
        pid = PIDController(kp=50.0, ki=0.1, kd=0.0, integral_max=100.0)

        pid.set_integral(50.0)
        assert pid.state.integral == 50.0

    def test_set_integral_respects_max(self) -> None:
        """Test that set_integral clamps so i_term stays within max."""
        # With ki=1.0, integral bounds map directly to % bounds
        pid = PIDController(ki=1.0, integral_max=100.0)

        pid.set_integral(150.0)
        # i_term = 1.0 * 150 = 150%, clamped to 100%, so integral = 100/1.0 = 100
        assert pid.state.integral == 100.0

    def test_set_integral_respects_min(self) -> None:
        """Test that set_integral clamps so i_term stays within min."""
        # With ki=1.0, integral bounds map directly to % bounds
        pid = PIDController(ki=1.0, integral_min=0.0, integral_max=100.0)

        pid.set_integral(-10.0)
        # i_term = 1.0 * -10 = -10%, clamped to 0%, so integral = 0/1.0 = 0
        assert pid.state.integral == 0.0

    def test_zero_dt(self) -> None:
        """Test that zero dt returns 0 output."""
        pid = PIDController(kp=50.0, ki=0.1, kd=1.0)

        output = pid.update(setpoint=22.0, current=20.0, dt=0.0)
        assert output == 0.0

    def test_negative_dt(self) -> None:
        """Test that negative dt returns 0 output."""
        pid = PIDController(kp=50.0, ki=0.1, kd=1.0)

        output = pid.update(setpoint=22.0, current=20.0, dt=-60.0)
        assert output == 0.0

    def test_get_terms(self) -> None:
        """Test get_terms returns correct breakdown."""
        pid = PIDController(kp=50.0, ki=1.0, kd=0.0, integral_max=1000.0)

        # First update to set some state (integral = 1 after one update with error=1)
        pid.update(setpoint=21.0, current=20.0, dt=60.0)

        terms = pid.get_terms(setpoint=21.0, current=20.0, dt=60.0)

        assert terms["error"] == 1.0
        assert terms["p_term"] == 50.0
        assert terms["i_term"] == pytest.approx(
            1.0
        )  # 1.0 * 1 (integral=1 after first update)
        assert terms["d_term"] == 0.0
        assert terms["output"] == pytest.approx(51.0)

    def test_get_terms_zero_dt(self) -> None:
        """Test get_terms with zero dt returns zeros."""
        pid = PIDController()

        terms = pid.get_terms(setpoint=21.0, current=20.0, dt=0.0)

        assert terms["error"] == 0.0
        assert terms["p_term"] == 0.0
        assert terms["i_term"] == 0.0
        assert terms["d_term"] == 0.0
        assert terms["output"] == 0.0

    def test_default_values(self) -> None:
        """Test default PID parameters match spec."""
        pid = PIDController()

        assert pid.kp == 50.0
        assert pid.ki == 0.05
        assert pid.kd == 0.0
        assert pid.integral_min == 0.0
        assert pid.integral_max == 100.0

    def test_state_property(self) -> None:
        """Test that state property returns correct state."""
        pid = PIDController()

        assert isinstance(pid.state, PIDState)
        assert pid.state.integral == 0.0
        assert pid.state.last_error == 0.0

    def test_combined_pid(self) -> None:
        """Test combined P, I, and D terms."""
        pid = PIDController(
            kp=10.0, ki=1.0, kd=1.0, integral_min=0.0, integral_max=1000.0
        )

        # First update
        output1 = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        # P = 10 * 2 = 20
        # I = 1.0 * 2 = 2 (integral accumulates error=2 once per interval)
        # D = 1 * (2 - 0) / 60 = 0.033
        expected = 20.0 + 2.0 + (1.0 * 2.0 / 60.0)
        assert output1 == pytest.approx(expected, rel=0.01)


class TestPIDState:
    """Test cases for PIDState dataclass."""

    def test_default_state(self) -> None:
        """Test default PIDState values."""
        state = PIDState()
        assert state.integral == 0.0
        assert state.last_error == 0.0

    def test_custom_state(self) -> None:
        """Test PIDState with custom values."""
        state = PIDState(integral=50.0, last_error=1.5)
        assert state.integral == 50.0
        assert state.last_error == 1.5
