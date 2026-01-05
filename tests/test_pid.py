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
        """Test that integral term accumulates over time."""
        pid = PIDController(kp=0.0, ki=0.1, kd=0.0, integral_max=1000.0)

        # First update: integral = 1 * 60 = 60
        output1 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state.integral == 60.0
        assert output1 == pytest.approx(6.0)  # 0.1 * 60 = 6

        # Second update: integral = 60 + 60 = 120
        output2 = pid.update(setpoint=21.0, current=20.0, dt=60.0)
        assert pid.state.integral == 120.0
        assert output2 == pytest.approx(12.0)  # 0.1 * 120 = 12

    def test_integral_anti_windup(self) -> None:
        """Test that integral is clamped to prevent windup."""
        pid = PIDController(
            kp=0.0, ki=0.1, kd=0.0, integral_min=0.0, integral_max=100.0
        )

        # Large error over long time should clamp integral
        output = pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert pid.state.integral == 100.0  # Clamped at max
        assert output == pytest.approx(10.0)  # 0.1 * 100 = 10

        # Further updates should not increase integral beyond max
        pid.update(setpoint=30.0, current=20.0, dt=60.0)
        assert pid.state.integral == 100.0

    def test_integral_anti_windup_negative(self) -> None:
        """Test that integral is clamped at minimum too."""
        pid = PIDController(
            kp=0.0, ki=0.1, kd=0.0, integral_min=-50.0, integral_max=100.0
        )

        # Negative error should drive integral down: -2 * 30 = -60, clamped to -50
        pid.update(setpoint=18.0, current=20.0, dt=30.0)
        assert pid.state.integral == -50.0

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
        pid = PIDController(kp=50.0, ki=0.1, kd=0.0, integral_max=1000.0)

        # First update to set some state
        pid.update(setpoint=21.0, current=20.0, dt=60.0)

        terms = pid.get_terms(setpoint=21.0, current=20.0, dt=60.0)

        assert terms["error"] == 1.0
        assert terms["p_term"] == 50.0
        assert terms["i_term"] == pytest.approx(6.0)  # 0.1 * 60
        assert terms["d_term"] == 0.0
        assert terms["output"] == pytest.approx(56.0)

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
            kp=10.0, ki=0.1, kd=1.0, integral_min=0.0, integral_max=1000.0
        )

        # First update
        output1 = pid.update(setpoint=22.0, current=20.0, dt=60.0)
        # P = 10 * 2 = 20
        # I = 0.1 * 120 = 12 (2 * 60 = 120)
        # D = 1 * (2 - 0) / 60 = 0.033
        expected = 20.0 + 12.0 + (1.0 * 2.0 / 60.0)
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
