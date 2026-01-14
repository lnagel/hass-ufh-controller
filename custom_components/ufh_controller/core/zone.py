"""
Zone state and decision logic for Underfloor Heating Controller.

This module contains the zone state dataclasses and decision functions
for determining valve actions based on quota-based scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from custom_components.ufh_controller.const import (
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DEFAULT_VALVE_OPEN_THRESHOLD,
    ValveState,
    ZoneStatus,
)


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
class TimingParams:
    """
    Timing parameters for zone scheduling.

    All durations are in seconds.
    """

    observation_period: int = DEFAULT_TIMING["observation_period"]
    min_run_time: int = DEFAULT_TIMING["min_run_time"]
    valve_open_time: int = DEFAULT_TIMING["valve_open_time"]
    closing_warning_duration: int = DEFAULT_TIMING["closing_warning_duration"]
    window_block_time: int = DEFAULT_TIMING["window_block_time"]
    controller_loop_interval: int = DEFAULT_TIMING["controller_loop_interval"]
    flush_duration: int = DEFAULT_TIMING["flush_duration"]


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
class ControllerState:
    """Runtime state for the entire controller."""

    mode: str = "auto"
    observation_start: datetime = field(default_factory=datetime.now)
    period_elapsed: float = 0.0  # Seconds elapsed in current observation period
    heat_request: bool = False
    flush_enabled: bool = False
    dhw_active: bool = False
    flush_until: datetime | None = None
    flush_request: bool = False
    zones: dict[str, ZoneState] = field(default_factory=dict)


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

    # Flush circuit priority during DHW heating or post-DHW flush period
    if (
        zone.circuit_type == CircuitType.FLUSH
        and controller.flush_enabled
        and controller.flush_request
        and not _any_regular_circuits_active(controller)
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


def aggregate_heat_request(
    zones: dict[str, ZoneState],
    timing: TimingParams,
) -> bool:
    """
    Aggregate heat request from all zones.

    Args:
        zones: Dictionary of zone states keyed by zone ID.
        timing: Timing parameters.

    Returns:
        True if any zone is requesting heat.

    """
    return any(should_request_heat(zone, timing) for zone in zones.values())


def _any_regular_circuits_active(controller: ControllerState) -> bool:
    """
    Check if any regular circuits are currently running (valve ON).

    Used for flush circuit priority - flush circuits only run
    when no regular circuits are actively heating. This allows
    flush circuits to capture DHW waste heat even when regular
    zones have heating demand but their valves are OFF due to
    DHW priority.
    """
    return any(
        zone.circuit_type == CircuitType.REGULAR
        and zone.enabled
        and zone.valve_state == ValveState.ON
        for zone in controller.zones.values()
    )
