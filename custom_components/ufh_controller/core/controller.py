"""
Controller logic for Underfloor Heating Controller.

This module provides the main HeatingController class that orchestrates
zone control, operation modes, and heat request aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from custom_components.ufh_controller.const import (
    DEFAULT_CYCLE_MODE_HOURS,
    SummerMode,
    TimingParams,
    ValveState,
)

from .pid import PIDController
from .zone import (
    CircuitType,
    ZoneAction,
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
    evaluate_zone,
    should_request_heat,
)


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


@dataclass
class ControllerConfig:
    """Configuration for the heating controller."""

    controller_id: str
    name: str
    heat_request_entity: str | None = None
    dhw_active_entity: str | None = None
    circulation_entity: str | None = None
    summer_mode_entity: str | None = None
    timing: TimingParams = field(default_factory=TimingParams)
    zones: list[ZoneConfig] = field(default_factory=list)


def compute_flush_request(
    *,
    flush_enabled: bool,
    dhw_active: bool,
    flush_until: datetime | None,
    any_regular_on: bool,
    now: datetime,
) -> bool:
    """
    Compute whether flush circuits should activate.

    Flush circuits activate when:
    - flush_enabled is True (user has enabled the feature)
    - DHW is active OR was recently active (within flush_until timer)
    - No regular circuits are currently ON

    Args:
        flush_enabled: User toggle for flush feature.
        dhw_active: Whether DHW is currently heating.
        flush_until: Post-DHW timer expiration, or None.
        any_regular_on: Whether any regular zones have valves ON.
        now: Current time for timer comparison.

    Returns:
        True if flush circuits should activate.

    """
    if not flush_enabled:
        return False

    # Check if DHW is active or was recently active
    dhw_or_recent = dhw_active or (flush_until is not None and now < flush_until)

    if not dhw_or_recent:
        return False

    # Flush only when no regular circuits are running
    return not any_regular_on


class HeatingController:
    """
    Main heating controller coordinating all zones.

    Implements the control loop that updates PID controllers,
    evaluates zone decisions, and aggregates heat requests.
    """

    def __init__(
        self,
        config: ControllerConfig,
    ) -> None:
        """
        Initialize the heating controller.

        Args:
            config: Controller configuration.

        """
        self.config = config
        self._state = ControllerState(mode="auto")
        self._zones: dict[str, ZoneRuntime] = {}

        # Initialize zones from config
        for zone_config in config.zones:
            self._zones[zone_config.zone_id] = ZoneRuntime(
                config=zone_config,
                pid=PIDController(
                    kp=zone_config.kp,
                    ki=zone_config.ki,
                    kd=zone_config.kd,
                    integral_min=zone_config.integral_min,
                    integral_max=zone_config.integral_max,
                ),
                state=ZoneState(
                    zone_id=zone_config.zone_id,
                    circuit_type=zone_config.circuit_type,
                    setpoint=zone_config.setpoint_default,
                ),
            )

    @property
    def state(self) -> ControllerState:
        """Get the current controller state."""
        return self._state

    @property
    def mode(self) -> str:
        """Get the current operation mode."""
        return self._state.mode

    @mode.setter
    def mode(self, value: str) -> None:
        """Set the operation mode."""
        self._state.mode = value

    def get_zone_state(self, zone_id: str) -> ZoneState | None:
        """Get the state of a specific zone."""
        runtime = self._zones.get(zone_id)
        return runtime.state if runtime else None

    def get_zone_runtime(self, zone_id: str) -> ZoneRuntime | None:
        """Get the runtime data for a specific zone."""
        return self._zones.get(zone_id)

    def set_zone_setpoint(self, zone_id: str, setpoint: float) -> bool:
        """
        Set the target temperature for a zone.

        Args:
            zone_id: Zone identifier.
            setpoint: Target temperature in degrees.

        Returns:
            True if setpoint was set, False if zone not found.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return False

        runtime.set_setpoint(setpoint)
        return True

    def set_zone_enabled(self, zone_id: str, *, enabled: bool) -> bool:
        """
        Enable or disable a zone.

        Args:
            zone_id: Zone identifier.
            enabled: Whether the zone should be enabled.

        Returns:
            True if state was set, False if zone not found.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return False
        runtime.set_enabled(enabled=enabled)
        return True

    def update_zone_pid(
        self,
        zone_id: str,
        current: float | None,
        dt: float,
    ) -> float | None:
        """
        Update the PID controller for a zone.

        Note: This is a thin delegator. The actual PID logic is in ZoneRuntime.
        This method exists for backwards compatibility with coordinator.

        Args:
            zone_id: Zone identifier.
            current: Current temperature reading (EMA-smoothed), or None.
            dt: Time delta since last update in seconds.

        Returns:
            The duty cycle (0-100), None if not yet calculated, or 0 if zone
            not found.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return 0.0

        # Set current temperature (coordinator has already applied EMA)
        runtime.state.current = current

        # Delegate PID update to zone
        return runtime.update_pid(dt, self._state.mode)

    def update_zone_historical(
        self,
        zone_id: str,
        *,
        period_state_avg: float,
        open_state_avg: float,
        window_recently_open: bool,
        elapsed_time: float,
    ) -> None:
        """
        Update zone historical averages from Recorder queries.

        Note: This is a thin delegator. The actual logic is in ZoneRuntime.
        This method exists for backwards compatibility with coordinator.

        Args:
            zone_id: Zone identifier.
            period_state_avg: Average valve state since observation start.
            open_state_avg: Average valve state for open detection.
            window_recently_open: Was any window open within blocking period.
            elapsed_time: Actual elapsed time since observation start in seconds.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return

        runtime.update_historical(
            period_state_avg=period_state_avg,
            open_state_avg=open_state_avg,
            window_recently_open=window_recently_open,
            elapsed_time=elapsed_time,
            observation_period=self.config.timing.observation_period,
        )

    def evaluate_zones(self, *, now: datetime) -> dict[str, ZoneAction]:
        """
        Evaluate all zones and determine valve actions.

        Evaluates regular zones first, then computes flush_request,
        then evaluates flush zones. This ensures flush circuits only
        activate when no regular circuits are running.

        Args:
            now: Current time for flush timer comparison.

        Returns:
            Dictionary mapping zone IDs to their actions.

        """
        actions: dict[str, ZoneAction] = {}

        # Build current controller state for decision logic
        self._state.zones = {zid: zr.state for zid, zr in self._zones.items()}

        # Phase 1: Evaluate regular zones first
        for zone_id, runtime in self._zones.items():
            if runtime.config.circuit_type == CircuitType.REGULAR:
                actions[zone_id] = self._evaluate_single_zone(zone_id, runtime)

        # Phase 2: Compute flush_request based on regular zone actions
        any_regular_on = any(
            action in {ZoneAction.TURN_ON, ZoneAction.STAY_ON}
            for zid, action in actions.items()
        )
        self._state.flush_request = compute_flush_request(
            flush_enabled=self._state.flush_enabled,
            dhw_active=self._state.dhw_active,
            flush_until=self._state.flush_until,
            any_regular_on=any_regular_on,
            now=now,
        )

        # Phase 3: Evaluate flush zones
        for zone_id, runtime in self._zones.items():
            if runtime.config.circuit_type == CircuitType.FLUSH:
                actions[zone_id] = self._evaluate_single_zone(zone_id, runtime)

        return actions

    def _evaluate_single_zone(
        self,
        zone_id: str,
        runtime: ZoneRuntime,
    ) -> ZoneAction:
        """Evaluate a single zone based on current mode."""
        mode = self._state.mode
        valve_on = runtime.state.valve_state == ValveState.ON

        if mode == "disabled":
            # Disabled mode - no action, maintain current state
            return ZoneAction.STAY_ON if valve_on else ZoneAction.STAY_OFF

        if mode == "all_on":
            return ZoneAction.STAY_ON if valve_on else ZoneAction.TURN_ON

        if mode == "all_off":
            return ZoneAction.TURN_OFF if valve_on else ZoneAction.STAY_OFF

        if mode == "flush":
            # Flush mode - all valves open
            return ZoneAction.STAY_ON if valve_on else ZoneAction.TURN_ON

        if mode == "cycle":
            return self._evaluate_cycle_mode(zone_id, runtime)

        # Default: auto mode - use decision tree
        return evaluate_zone(runtime.state, self._state, self.config.timing)

    def _evaluate_cycle_mode(
        self,
        zone_id: str,
        runtime: ZoneRuntime,
    ) -> ZoneAction:
        """Evaluate zone action for cycle mode."""
        # Get current hour of day
        now = datetime.now(UTC)
        cycle_hour = now.hour % DEFAULT_CYCLE_MODE_HOURS
        valve_on = runtime.state.valve_state == ValveState.ON

        if cycle_hour == 0:
            # Rest hour - all closed
            return ZoneAction.TURN_OFF if valve_on else ZoneAction.STAY_OFF

        # Determine which zone should be active
        zone_ids = list(self._zones.keys())
        if not zone_ids:
            return ZoneAction.STAY_OFF

        active_index = (cycle_hour - 1) % len(zone_ids)
        active_zone_id = zone_ids[active_index]

        if zone_id == active_zone_id:
            return ZoneAction.TURN_ON if not valve_on else ZoneAction.STAY_ON
        return ZoneAction.TURN_OFF if valve_on else ZoneAction.STAY_OFF

    def calculate_heat_request(self) -> bool:
        """
        Calculate aggregate heat request from all zones.

        Returns:
            True if any zone is requesting heat.

        """
        if self._state.mode == "disabled":
            return False

        if self._state.mode == "all_off":
            return False

        if self._state.mode in ("all_on", "flush"):
            # These modes control heat differently
            return self._state.mode == "all_on"

        # Auto and cycle modes use zone-based logic
        zone_states = {zid: zr.state for zid, zr in self._zones.items()}
        return aggregate_heat_request(zone_states, self.config.timing)

    def get_summer_mode_value(self, *, heat_request: bool) -> str | None:
        """
        Determine the summer mode value for the boiler.

        Args:
            heat_request: Current heat request state.

        Returns:
            SummerMode.WINTER for heating, SummerMode.SUMMER for no heating,
            or None if not applicable.

        """
        if self.config.summer_mode_entity is None:
            return None

        mode = self._state.mode

        if mode == "disabled":
            return None

        if mode in ("flush", "all_off"):
            return SummerMode.SUMMER

        if mode == "all_on":
            return SummerMode.WINTER

        # Auto and cycle modes depend on heat request
        return SummerMode.WINTER if heat_request else SummerMode.SUMMER

    @property
    def zone_ids(self) -> list[str]:
        """Get list of all zone IDs."""
        return list(self._zones.keys())


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
