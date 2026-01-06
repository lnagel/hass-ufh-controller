"""
PID controller implementation for UFH Controller.

This module provides a pure Python PID controller with anti-windup
for temperature regulation in heating zones.
"""

from dataclasses import dataclass, field


@dataclass
class PIDState:
    """
    State of the PID controller.

    The integral is stored in % units (post-ki multiplication) so that
    changing ki does not immediately affect the accumulated contribution.
    """

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
        integral_min: Minimum integral term contribution in % (anti-windup).
        integral_max: Maximum integral term contribution in % (anti-windup).

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

        The integral accumulates once per call (per controller interval),
        not multiplied by time. This is appropriate for slow thermal processes
        like underfloor heating where the integral should be in % units
        matching the proportional term.

        Args:
            setpoint: Target temperature.
            current: Current temperature.
            dt: Time delta in seconds since last update (used for derivative term).

        Returns:
            Duty cycle as a percentage (0.0 to 100.0).

        """
        if dt <= 0:
            return 0.0

        error = setpoint - current

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup (accumulates per interval, not per second)
        # Integral is stored in % units so changing ki doesn't affect accumulated value
        self._state.integral += self.ki * error
        self._state.integral = max(
            self.integral_min, min(self.integral_max, self._state.integral)
        )
        i_term = self._state.integral

        # Derivative term
        d_term = self.kd * (error - self._state.last_error) / dt
        self._state.last_error = error

        # Output clamped to 0-100%
        output = p_term + i_term + d_term
        return max(0.0, min(100.0, output))

    def reset(self) -> None:
        """Reset the PID controller state."""
        self._state = PIDState()

    def set_integral(self, value: float) -> None:
        """
        Set the integral value directly (for state restoration).

        The value is in % units (the i_term contribution) and is clamped
        to [integral_min, integral_max].
        """
        self._state.integral = max(self.integral_min, min(self.integral_max, value))

    def set_last_error(self, value: float) -> None:
        """Set the last error value directly (for state restoration)."""
        self._state.last_error = value

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
        i_term = self._state.integral  # Already in % units
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
