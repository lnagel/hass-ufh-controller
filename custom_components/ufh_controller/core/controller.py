"""
Controller logic for Underfloor Heating Controller.

This module provides the main HeatingController class that orchestrates
zone control, operation modes, and heat request aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from custom_components.ufh_controller.const import (
    DEFAULT_CYCLE_MODE_HOURS,
    OperationMode,
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
)


@dataclass
class ControllerState:
    """Runtime state for the entire controller."""

    mode: OperationMode = OperationMode.AUTO
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


@dataclass
class ControllerActions:
    """
    All actions computed by the controller for execution.

    The coordinator executes these actions via Home Assistant services.
    Optional fields (heat_request, summer_mode) are None when no change is needed.
    """

    valve_actions: dict[str, ZoneAction]
    heat_request: ValveState | None = None  # ON/OFF, or None if no change needed
    summer_mode: SummerMode | None = None  # winter/summer/auto, or None if no change


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
        self._state = ControllerState(mode=OperationMode.AUTO)
        self._zones: dict[str, ZoneRuntime] = {}

        # Track previous states for change detection
        self._prev_heat_request: bool = False
        self._prev_summer_mode: str | None = None

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
    def mode(self) -> OperationMode:
        """Get the current operation mode."""
        return self._state.mode

    @mode.setter
    def mode(self, value: str | OperationMode) -> None:
        """Set the operation mode."""
        self._state.mode = OperationMode(value)

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

    # -------------------------------------------------------------------------
    # Mode-specific evaluation functions
    # -------------------------------------------------------------------------

    def _evaluate_disabled_mode(self) -> ControllerActions:
        """
        Disabled mode - no changes whatsoever.

        Returns empty valve actions - no state detection, no changes.
        """
        return ControllerActions(valve_actions={})

    def _evaluate_all_on_mode(self) -> ControllerActions:
        """
        All-on mode - all valves open, boiler fires.

        Permanently heating: heat_request=ON, summer_mode=WINTER.
        """
        valve_actions = {
            zid: (
                ZoneAction.STAY_ON
                if rt.state.valve_state == ValveState.ON
                else ZoneAction.TURN_ON
            )
            for zid, rt in self._zones.items()
        }
        return ControllerActions(
            valve_actions=valve_actions,
            heat_request=ValveState.ON,
            summer_mode=SummerMode.WINTER,
        )

    def _evaluate_all_off_mode(self) -> ControllerActions:
        """
        All-off mode - all valves closed, no heating.

        Permanently not heating: heat_request=OFF, summer_mode=SUMMER.
        """
        valve_actions = {
            zid: (
                ZoneAction.TURN_OFF
                if rt.state.valve_state == ValveState.ON
                else ZoneAction.STAY_OFF
            )
            for zid, rt in self._zones.items()
        }
        return ControllerActions(
            valve_actions=valve_actions,
            heat_request=ValveState.OFF,
            summer_mode=SummerMode.SUMMER,
        )

    def _evaluate_flush_mode(self) -> ControllerActions:
        """
        Flush mode - all valves open, circulation only (no boiler firing).

        Permanently not heating: heat_request=OFF, summer_mode=SUMMER.
        """
        valve_actions = {
            zid: (
                ZoneAction.STAY_ON
                if rt.state.valve_state == ValveState.ON
                else ZoneAction.TURN_ON
            )
            for zid, rt in self._zones.items()
        }
        return ControllerActions(
            valve_actions=valve_actions,
            heat_request=ValveState.OFF,
            summer_mode=SummerMode.SUMMER,
        )

    def _evaluate_cycle_mode(self, now: datetime) -> ControllerActions:
        """
        Cycle mode - rotate through zones by hour, circulation only.

        Same as flush mode but one zone at a time on an 8-hour rotation.
        Hour 0: all closed (rest hour)
        Hours 1-7: zones open sequentially

        Permanently not heating: heat_request=OFF, summer_mode=SUMMER.
        """
        cycle_hour = now.hour % DEFAULT_CYCLE_MODE_HOURS
        zone_ids = list(self._zones.keys())

        valve_actions: dict[str, ZoneAction] = {}
        for zid, rt in self._zones.items():
            valve_on = rt.state.valve_state == ValveState.ON
            if cycle_hour == 0:
                # Rest hour - all closed
                valve_actions[zid] = (
                    ZoneAction.TURN_OFF if valve_on else ZoneAction.STAY_OFF
                )
            elif not zone_ids:
                valve_actions[zid] = ZoneAction.STAY_OFF
            else:
                active_index = (cycle_hour - 1) % len(zone_ids)
                if zid == zone_ids[active_index]:
                    valve_actions[zid] = (
                        ZoneAction.STAY_ON if valve_on else ZoneAction.TURN_ON
                    )
                else:
                    valve_actions[zid] = (
                        ZoneAction.TURN_OFF if valve_on else ZoneAction.STAY_OFF
                    )

        return ControllerActions(
            valve_actions=valve_actions,
            heat_request=ValveState.OFF,
            summer_mode=SummerMode.SUMMER,
        )

    def _evaluate_auto_mode(self, now: datetime) -> ControllerActions:
        """
        Auto mode - quota-based scheduling with flush circuit logic.

        Uses PID-based quota scheduling for regular zones, then evaluates
        flush circuits based on whether any regular zones are running.

        Heat request and summer mode are calculated from zone outputs.
        """
        valve_actions = self._evaluate_auto_valves(now)

        # Calculate heat request from zone outputs
        heat_request = any(
            rt.should_request_heat(self.config.timing) for rt in self._zones.values()
        )

        # Apply change detection for auto mode
        heat_request_action: ValveState | None = None
        if heat_request != self._prev_heat_request:
            heat_request_action = ValveState.ON if heat_request else ValveState.OFF
            self._prev_heat_request = heat_request

        summer_mode = SummerMode.WINTER if heat_request else SummerMode.SUMMER
        summer_mode_action: SummerMode | None = None
        if summer_mode != self._prev_summer_mode:
            summer_mode_action = summer_mode
            self._prev_summer_mode = summer_mode

        return ControllerActions(
            valve_actions=valve_actions,
            heat_request=heat_request_action,
            summer_mode=summer_mode_action,
        )

    def evaluate_zones(self, *, now: datetime) -> dict[str, ZoneAction]:
        """
        Evaluate all zones and determine valve actions.

        This method is maintained for backwards compatibility. It returns
        only valve actions (not heat_request or summer_mode).

        For full evaluation with all actions, use evaluate() instead.

        Args:
            now: Current time for flush timer comparison.

        Returns:
            Dictionary mapping zone IDs to their actions.

        """
        # Delegate to evaluate() and extract valve actions
        actions = self.evaluate(now=now)
        return actions.valve_actions

    def _evaluate_auto_valves(self, now: datetime) -> dict[str, ZoneAction]:
        """
        Evaluate all zones in auto mode using quota-based scheduling.

        Evaluates regular zones first, then computes flush_request,
        then evaluates flush zones. This ensures flush circuits only
        activate when no regular circuits are running.

        Args:
            now: Current time for flush timer comparison.

        Returns:
            Dictionary mapping zone IDs to their actions.

        """
        actions: dict[str, ZoneAction] = {}

        # Phase 1: Evaluate regular zones first using quota-based scheduling
        for zone_id, runtime in self._zones.items():
            if runtime.config.circuit_type == CircuitType.REGULAR:
                actions[zone_id] = runtime.evaluate(self._state, self.config.timing)

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
                actions[zone_id] = runtime.evaluate(self._state, self.config.timing)

        return actions

    def evaluate(self, *, now: datetime) -> ControllerActions:
        """
        Evaluate all zones and compute all controller actions.

        This is the main entry point for the control loop. Dispatches to
        mode-specific evaluation functions that return complete ControllerActions.

        Args:
            now: Current time for flush timer and cycle mode calculation.

        Returns:
            ControllerActions with valve actions and optional state changes.

        """
        mode = self._state.mode
        if mode == OperationMode.DISABLED:
            return self._evaluate_disabled_mode()
        if mode == OperationMode.ALL_ON:
            return self._evaluate_all_on_mode()
        if mode == OperationMode.ALL_OFF:
            return self._evaluate_all_off_mode()
        if mode == OperationMode.FLUSH:
            return self._evaluate_flush_mode()
        if mode == OperationMode.CYCLE:
            return self._evaluate_cycle_mode(now)
        # Default: auto mode
        return self._evaluate_auto_mode(now)

    def calculate_heat_request(self) -> bool:
        """
        Calculate aggregate heat request from all zones.

        Returns:
            True if any zone is requesting heat.

        """
        if self._state.mode == OperationMode.DISABLED:
            return False

        if self._state.mode == OperationMode.ALL_OFF:
            return False

        if self._state.mode in (OperationMode.ALL_ON, OperationMode.FLUSH):
            # These modes control heat differently
            return self._state.mode == OperationMode.ALL_ON

        # Auto and cycle modes use zone-based logic
        return any(
            runtime.should_request_heat(self.config.timing)
            for runtime in self._zones.values()
        )

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

        if mode == OperationMode.DISABLED:
            return None

        if mode in (OperationMode.FLUSH, OperationMode.ALL_OFF):
            return SummerMode.SUMMER

        if mode == OperationMode.ALL_ON:
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

    Note: This function is kept for backwards compatibility.
    Prefer using ZoneRuntime.should_request_heat() method directly.

    Args:
        zones: Dictionary of zone states keyed by zone ID.
        timing: Timing parameters.

    Returns:
        True if any zone is requesting heat.

    """
    from .zone import should_request_heat  # noqa: PLC0415

    return any(should_request_heat(zone, timing) for zone in zones.values())
