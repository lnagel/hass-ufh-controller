"""
Zone state and decision logic for Underfloor Heating Controller.

This module contains the zone state dataclasses and decision functions
for determining valve actions based on quota-based scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TEMP_EMA_TIME_CONSTANT,
    DEFAULT_VALVE_OPEN_THRESHOLD,
    TimingParams,
    ValveState,
    ZoneStatus,
)

from .ema import apply_ema

if TYPE_CHECKING:
    from datetime import datetime

    from .controller import ControllerState
    from .pid import PIDController


class CircuitType(StrEnum):
    """Type of heating circuit."""

    REGULAR = "regular"
    FLUSH = "flush"


class ZoneAction(StrEnum):
    """Actions that can be taken on a zone valve."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    STAY_ON = "stay_on"
    STAY_OFF = "stay_off"


@dataclass
class ZoneState:
    """
    Runtime state for a single zone.

    Contains valve state, historical averages, and derived scheduling values.
    PID state is stored separately in PIDController.state.
    """

    zone_id: str
    circuit_type: CircuitType = CircuitType.REGULAR

    # Temperature state
    current: float | None = None
    setpoint: float = DEFAULT_SETPOINT["default"]

    # Valve state
    valve_state: ValveState = ValveState.UNKNOWN
    valve_on_since: datetime | None = None

    # Historical averages from Recorder queries
    period_state_avg: float = 0.0
    open_state_avg: float = 0.0
    window_recently_open: bool = False  # Was any window open within blocking period

    # Derived scheduling values
    used_duration: float = 0.0
    requested_duration: float = 0.0

    # Zone enabled state
    enabled: bool = True

    # Zone fault isolation state
    zone_status: ZoneStatus = ZoneStatus.INITIALIZING
    last_successful_update: datetime | None = None
    consecutive_failures: int = 0


@dataclass
class ZoneConfig:
    """Configuration for a single zone."""

    zone_id: str
    name: str
    temp_sensor: str
    valve_switch: str
    circuit_type: CircuitType = CircuitType.REGULAR
    window_sensors: list[str] = field(default_factory=list)
    setpoint_min: float = DEFAULT_SETPOINT["min"]
    setpoint_max: float = DEFAULT_SETPOINT["max"]
    setpoint_default: float = DEFAULT_SETPOINT["default"]
    kp: float = DEFAULT_PID["kp"]
    ki: float = DEFAULT_PID["ki"]
    kd: float = DEFAULT_PID["kd"]
    integral_min: float = DEFAULT_PID["integral_min"]
    integral_max: float = DEFAULT_PID["integral_max"]
    temp_ema_time_constant: int = DEFAULT_TEMP_EMA_TIME_CONSTANT


class ZoneRuntime:
    """
    Runtime data for a zone including PID controller and state.

    This class owns the zone's configuration, PID controller, and mutable state.
    It provides methods for updating temperature, PID, and historical data.
    """

    def __init__(
        self,
        config: ZoneConfig,
        pid: PIDController,
        state: ZoneState,
        last_update: datetime | None = None,
    ) -> None:
        """
        Initialize zone runtime.

        Args:
            config: Zone configuration (immutable).
            pid: PID controller instance.
            state: Zone state (mutable).
            last_update: Timestamp of last update.

        """
        self.config = config
        self.pid = pid
        self.state = state
        self.last_update = last_update

    def update_temperature(self, raw_temp: float | None, dt: float) -> None:
        """
        Update zone temperature with EMA smoothing.

        Args:
            raw_temp: Raw temperature reading from sensor, or None if unavailable.
            dt: Time delta since last update in seconds.

        """
        if raw_temp is None:
            return

        self.state.current = apply_ema(
            current=raw_temp,
            previous=self.state.current,
            tau=self.config.temp_ema_time_constant,
            dt=dt,
        )

    def update_pid(self, dt: float, controller_mode: str) -> float | None:
        """
        Update the PID controller for this zone.

        PID integration is paused (no update called) when:
        - Temperature reading is unavailable
        - Controller mode is not 'auto' (PID only meaningful in auto mode)
        - Zone is disabled
        - Window was open recently (within blocking period)

        Args:
            dt: Time delta since last update in seconds.
            controller_mode: Current controller operation mode.

        Returns:
            The duty cycle (0-100), None if not yet calculated.

        """
        if self.state.current is None:
            # No temperature reading - maintain last duty cycle
            return self.pid.state.duty_cycle if self.pid.state else None

        if self._should_pause_pid(controller_mode):
            return self.pid.state.duty_cycle if self.pid.state else None

        pid_state = self.pid.update(
            setpoint=self.state.setpoint,
            current=self.state.current,
            dt=dt,
        )

        return pid_state.duty_cycle

    def _should_pause_pid(self, controller_mode: str) -> bool:
        """
        Check if PID integration should be paused.

        Args:
            controller_mode: Current controller operation mode.

        Returns:
            True if PID should be paused.

        """
        # Only auto mode uses PID-based control
        if controller_mode != "auto":
            return True

        # Disabled zones shouldn't accumulate integral
        if not self.state.enabled:
            return True

        # Window was open recently - pause PID to let temperature stabilize
        return self.state.window_recently_open

    def update_historical(
        self,
        *,
        period_state_avg: float,
        open_state_avg: float,
        window_recently_open: bool,
        elapsed_time: float,
        observation_period: int,
    ) -> None:
        """
        Update zone historical averages from Recorder queries.

        Args:
            period_state_avg: Average valve state since observation start.
            open_state_avg: Average valve state for open detection.
            window_recently_open: Was any window open within blocking period.
            elapsed_time: Actual elapsed time since observation start in seconds.
            observation_period: Full observation period in seconds.

        """
        self.state.period_state_avg = period_state_avg
        self.state.open_state_avg = open_state_avg
        self.state.window_recently_open = window_recently_open

        # Calculate used and requested durations
        self.state.used_duration = period_state_avg * elapsed_time
        duty_cycle = self.pid.state.duty_cycle if self.pid.state else 0.0
        self.state.requested_duration = calculate_requested_duration(
            duty_cycle,
            observation_period,
        )

    def set_setpoint(self, setpoint: float) -> None:
        """
        Set the target temperature, clamped to configured limits.

        Args:
            setpoint: Target temperature in degrees.

        """
        clamped = max(
            self.config.setpoint_min,
            min(self.config.setpoint_max, setpoint),
        )
        self.state.setpoint = clamped

    def set_enabled(self, *, enabled: bool) -> None:
        """
        Enable or disable this zone.

        Args:
            enabled: Whether the zone should be enabled.

        """
        self.state.enabled = enabled


def calculate_requested_duration(
    duty_cycle: float | None,
    observation_period: int,
) -> float:
    """
    Calculate how many seconds a valve should run based on duty cycle.

    Args:
        duty_cycle: PID output as percentage (0-100), or None if not yet calculated.
        observation_period: Total observation period in seconds.

    Returns:
        Number of seconds the valve should run in this period.
        Returns 0.0 if duty_cycle is None (not yet calculated).

    """
    if duty_cycle is None:
        return 0.0
    return (duty_cycle / 100.0) * observation_period


def evaluate_zone(  # noqa: PLR0911
    zone: ZoneState,
    controller: ControllerState,
    timing: TimingParams,
) -> ZoneAction:
    """
    Evaluate zone state and determine valve action.

    Implements quota-based scheduling and flush circuit priority.
    Note: Window blocking is handled via PID pause, not valve control.

    Args:
        zone: Current zone state.
        controller: Current controller state.
        timing: Timing parameters.

    Returns:
        The action to take on the zone valve.

    """
    valve_on = zone.valve_state == ValveState.ON
    valve_off = zone.valve_state == ValveState.OFF

    # Zone disabled - always off
    if not zone.enabled:
        return ZoneAction.STAY_OFF if valve_off else ZoneAction.TURN_OFF

    # Flush circuit activation
    if (
        zone.circuit_type == CircuitType.FLUSH
        and controller.flush_enabled
        and controller.flush_request
    ):
        return ZoneAction.TURN_ON if not valve_on else ZoneAction.STAY_ON

    # Near end of observation period - freeze valve positions to avoid cycling
    # If time remaining is less than min_run_time, a state change would be too brief
    time_remaining = timing.observation_period - controller.period_elapsed
    if time_remaining < timing.min_run_time:
        if valve_on:
            return ZoneAction.STAY_ON
        return ZoneAction.STAY_OFF if valve_off else ZoneAction.TURN_OFF

    # Quota-based scheduling
    if zone.used_duration < zone.requested_duration:
        # Zone still needs heating this period

        if valve_on:
            # Already on - stay on (re-send to prevent relay timeout)
            return ZoneAction.STAY_ON

        remaining_quota = zone.requested_duration - zone.used_duration
        if remaining_quota < timing.min_run_time:
            # Not enough quota left to justify turning on
            return ZoneAction.STAY_OFF if valve_off else ZoneAction.TURN_OFF

        if controller.dhw_active and zone.circuit_type == CircuitType.REGULAR:
            # Wait for DHW heating to finish
            return ZoneAction.STAY_OFF if valve_off else ZoneAction.TURN_OFF

        # Turn on
        return ZoneAction.TURN_ON

    # Zone has met its quota
    return ZoneAction.STAY_OFF if valve_off else ZoneAction.TURN_OFF


def should_request_heat(
    zone: ZoneState,
    timing: TimingParams,
) -> bool:
    """
    Determine if a zone should contribute to heat request.

    Heat is only requested when the valve is confirmed open and has been
    open long enough to be fully open. When valve state is unknown or
    unavailable, heat is NOT requested (conservative approach).

    Args:
        zone: Current zone state.
        timing: Timing parameters.

    Returns:
        True if zone should request heat from boiler.

    """
    # Only request heat when valve state is confirmed ON
    if zone.valve_state != ValveState.ON:
        return False

    if not zone.enabled:
        return False

    # Wait for valve to fully open
    if zone.open_state_avg < DEFAULT_VALVE_OPEN_THRESHOLD:
        return False

    # Don't request if zone is about to close
    remaining_quota = zone.requested_duration - zone.used_duration
    return remaining_quota >= timing.closing_warning_duration
