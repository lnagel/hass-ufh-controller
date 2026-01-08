"""
Zone state and decision logic for UFH Controller.

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
    duty_cycle_window: int = DEFAULT_TIMING["duty_cycle_window"]
    min_run_time: int = DEFAULT_TIMING["min_run_time"]
    valve_open_time: int = DEFAULT_TIMING["valve_open_time"]
    closing_warning_duration: int = DEFAULT_TIMING["closing_warning_duration"]
    window_block_threshold: float = DEFAULT_TIMING["window_block_threshold"]
    controller_loop_interval: int = DEFAULT_TIMING["controller_loop_interval"]


@dataclass
class ZoneState:
    """
    Runtime state for a single zone.

    Contains PID state, valve state, historical averages,
    and derived scheduling values.
    """

    zone_id: str
    circuit_type: CircuitType = CircuitType.REGULAR

    # PID state
    current: float | None = None
    setpoint: float = DEFAULT_SETPOINT["default"]
    error: float | None = None
    p_term: float | None = None
    i_term: float | None = None
    d_term: float | None = None
    duty_cycle: float | None = None

    # Valve state
    valve_on: bool = False
    valve_on_since: datetime | None = None

    # Historical averages from Recorder queries
    duty_cycle_avg: float = 0.0
    period_state_avg: float = 0.0
    open_state_avg: float = 0.0
    window_open_avg: float = 0.0

    # Derived scheduling values
    used_duration: float = 0.0
    requested_duration: float = 0.0

    # Zone enabled state
    enabled: bool = True

    @property
    def is_window_blocked(self) -> bool:
        """Check if zone is blocked by window/door sensor."""
        # This is computed by evaluate_zone based on threshold
        return False

    @property
    def is_requesting_heat(self) -> bool:
        """Check if zone is contributing to heat request."""
        # This is computed by should_request_heat
        return False


@dataclass
class ControllerState:
    """Runtime state for the entire controller."""

    mode: str = "auto"
    observation_start: datetime = field(default_factory=datetime.now)
    heat_request: bool = False
    flush_enabled: bool = False
    dhw_active: bool = False
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

    Implements quota-based scheduling with window blocking
    and flush circuit priority.

    Args:
        zone: Current zone state.
        controller: Current controller state.
        timing: Timing parameters.

    Returns:
        The action to take on the zone valve.

    """
    # Zone disabled - always off
    if not zone.enabled:
        return ZoneAction.TURN_OFF if zone.valve_on else ZoneAction.STAY_OFF

    # Flush circuit priority during DHW heating
    if (
        zone.circuit_type == CircuitType.FLUSH
        and controller.flush_enabled
        and controller.dhw_active
        and not _any_regular_circuits_active(controller)
    ):
        return ZoneAction.TURN_ON if not zone.valve_on else ZoneAction.STAY_ON

    # Window blocking
    if zone.window_open_avg > timing.window_block_threshold:
        return ZoneAction.TURN_OFF if zone.valve_on else ZoneAction.STAY_OFF

    # Quota-based scheduling
    if zone.used_duration < zone.requested_duration:
        # Zone still needs heating this period

        if zone.valve_on:
            # Already on - stay on (re-send to prevent relay timeout)
            return ZoneAction.STAY_ON

        remaining_quota = zone.requested_duration - zone.used_duration
        if remaining_quota < timing.min_run_time:
            # Not enough quota left to justify turning on
            return ZoneAction.STAY_OFF

        if controller.dhw_active and zone.circuit_type == CircuitType.REGULAR:
            # Wait for DHW heating to finish
            return ZoneAction.STAY_OFF

        # Turn on
        return ZoneAction.TURN_ON

    # Zone has met its quota
    return ZoneAction.TURN_OFF if zone.valve_on else ZoneAction.STAY_OFF


def should_request_heat(
    zone: ZoneState,
    timing: TimingParams,
) -> bool:
    """
    Determine if a zone should contribute to heat request.

    Heat is only requested when the valve is open and has been
    open long enough to be fully open.

    Args:
        zone: Current zone state.
        timing: Timing parameters.

    Returns:
        True if zone should request heat from boiler.

    """
    if not zone.valve_on:
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
    Check if any regular circuits have heating demand.

    Used for flush circuit priority - flush circuits only run
    during DHW when no regular circuits need heat.
    """
    return any(
        zone.circuit_type == CircuitType.REGULAR
        and zone.enabled
        and zone.requested_duration > 0
        for zone in controller.zones.values()
    )
