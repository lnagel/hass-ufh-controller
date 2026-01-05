"""
PID controller implementation for UFH Controller.

This module provides a pure Python PID controller with anti-windup
for temperature regulation in heating zones.
"""

from dataclasses import dataclass, field


@dataclass
class PIDState:
    """State of the PID controller."""

    integral: float = 0.0
    last_error: float = 0.0


@dataclass
class PIDController:
    """
    PID controller with anti-windup for temperature control.

    The controller calculates a duty cycle (0-100%) based on the
    temperature error (setpoint - current temperature).

    Attributes:
        kp: Proportional gain.
        ki: Integral gain.
        kd: Derivative gain.
        integral_min: Minimum integral value (anti-windup).
        integral_max: Maximum integral value (anti-windup).

    """

    kp: float = 50.0
    ki: float = 0.05
    kd: float = 0.0
    integral_min: float = 0.0
    integral_max: float = 100.0

    _state: PIDState = field(default_factory=PIDState, init=False, repr=False)

    @property
    def state(self) -> PIDState:
        """Return the current PID state."""
        return self._state

    def update(self, setpoint: float, current: float, dt: float) -> float:
        """
        Calculate duty cycle from temperature error.

        Args:
            setpoint: Target temperature.
            current: Current temperature.
            dt: Time delta in seconds since last update.

        Returns:
            Duty cycle as a percentage (0.0 to 100.0).

        """
        if dt <= 0:
            return 0.0

        error = setpoint - current

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup
        self._state.integral += error * dt
        self._state.integral = max(
            self.integral_min, min(self.integral_max, self._state.integral)
        )
        i_term = self.ki * self._state.integral

        # Derivative term
        d_term = self.kd * (error - self._state.last_error) / dt
        self._state.last_error = error

        # Output clamped to 0-100%
        output = p_term + i_term + d_term
        return max(0.0, min(100.0, output))

    def reset(self) -> None:
        """Reset the PID controller state."""
        self._state = PIDState()

    def get_terms(self, setpoint: float, current: float, dt: float) -> dict[str, float]:
        """
        Calculate and return individual PID terms without updating state.

        This is useful for diagnostic purposes.

        Args:
            setpoint: Target temperature.
            current: Current temperature.
            dt: Time delta in seconds since last update.

        Returns:
            Dictionary with 'error', 'p_term', 'i_term', 'd_term', and 'output'.

        """
        if dt <= 0:
            return {
                "error": 0.0,
                "p_term": 0.0,
                "i_term": 0.0,
                "d_term": 0.0,
                "output": 0.0,
            }

        error = setpoint - current
        p_term = self.kp * error
        i_term = self.ki * self._state.integral
        d_term = (
            self.kd * (error - self._state.last_error) / dt if self.kd != 0 else 0.0
        )

        output = p_term + i_term + d_term
        output = max(0.0, min(100.0, output))

        return {
            "error": error,
            "p_term": p_term,
            "i_term": i_term,
            "d_term": d_term,
            "output": output,
        }
