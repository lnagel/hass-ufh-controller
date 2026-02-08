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
    INITIALIZING_TIMEOUT,
    ControllerStatus,
    OperationMode,
    SummerMode,
    TimingConfig,
    ValveState,
    ZoneStatus,
)

from .heating_curve import HeatingCurveConfig, calculate_supply_target
from .pid import PIDController
from .zone import (
    CircuitType,
    ZoneAction,
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
    evaluate_zone,
)


@dataclass
class ControllerState:
    """Runtime state for the entire controller."""

    started_at: datetime  # Required, provided by caller (no side effects)
    status: ControllerStatus = ControllerStatus.INITIALIZING
    mode: OperationMode = OperationMode.HEAT
    observation_start: datetime = field(default_factory=datetime.now)
    period_elapsed: float = 0.0  # Seconds elapsed in current observation period
    heat_request: bool | None = None
    flush_enabled: bool = False
    dhw_active: bool = False
    flush_until: datetime | None = None
    flush_request: bool = False
    zones: dict[str, ZoneState] = field(default_factory=dict)
    outdoor_temp: float | None = None
    supply_target_temp: float | None = None


@dataclass
class ControllerConfig:
    """Configuration for the heating controller."""

    controller_id: str
    name: str
    heat_request_entity: str | None = None
    dhw_active_entity: str | None = None
    summer_mode_entity: str | None = None
    supply_temp_entity: str | None = None
    outdoor_temp_entity: str | None = None
    heating_curve: HeatingCurveConfig = field(default_factory=HeatingCurveConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    zones: list[ZoneConfig] = field(default_factory=list)


@dataclass
class ControllerActions:
    """
    All actions computed by the controller for execution.

    The coordinator executes these actions via Home Assistant services.
    """

    valve_actions: dict[str, ZoneAction] = field(default_factory=dict)
    heat_request: bool | None = None
    flush_request: bool = False


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
    - DHW is NOT currently active
    - Post-DHW timer is active
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

    if dhw_active:
        return False

    if flush_until is None or now >= flush_until:
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
        *,
        started_at: datetime,
    ) -> None:
        """
        Initialize the heating controller.

        Args:
            config: Controller configuration.
            started_at: Current time for initialization timestamp.

        """
        self.config = config
        self._state = ControllerState(started_at=started_at, mode=OperationMode.HEAT)
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
    def mode(self) -> OperationMode:
        """Get the current operation mode."""
        return self._state.mode

    @mode.setter
    def mode(self, value: str | OperationMode) -> None:
        """Set the operation mode."""
        self._state.mode = OperationMode(value)

    @property
    def status(self) -> ControllerStatus:
        """Get the current controller operational status."""
        return self._state.status

    def update_status(self, *, now: datetime, has_pending_entities: bool) -> None:
        """Update controller status based on zone statuses."""
        # Defer transition out of INITIALIZING while entities haven't reported
        if self._state.status == ControllerStatus.INITIALIZING and has_pending_entities:
            elapsed = (now - self._state.started_at).total_seconds()
            if elapsed < INITIALIZING_TIMEOUT:
                return  # remain INITIALIZING

        # Zone status aggregation
        zone_statuses = [rt.state.zone_status for rt in self._zones.values()]

        if not zone_statuses:
            self._state.status = ControllerStatus.NORMAL
            return

        # Count zones in each state
        initializing_count = sum(
            1 for s in zone_statuses if s == ZoneStatus.INITIALIZING
        )
        normal_count = sum(1 for s in zone_statuses if s == ZoneStatus.NORMAL)
        fail_safe_count = sum(1 for s in zone_statuses if s == ZoneStatus.FAIL_SAFE)
        degraded_count = sum(1 for s in zone_statuses if s == ZoneStatus.DEGRADED)

        # Controller status logic:
        # - If ALL zones are initializing → controller initializing
        # - If ANY zone is normal → controller operational (degraded if others fail)
        # - If ANY zone is still initializing → don't go to fail-safe yet
        # - Only go to fail-safe if ALL zones are in fail-safe

        if initializing_count == len(zone_statuses):
            # All zones still initializing - controller is initializing
            self._state.status = ControllerStatus.INITIALIZING
        elif normal_count > 0:
            # At least one zone is normal - controller is operational
            if fail_safe_count > 0 or degraded_count > 0:
                self._state.status = ControllerStatus.DEGRADED
            else:
                self._state.status = ControllerStatus.NORMAL
        elif initializing_count > 0:
            # Some zones still initializing, rest are degraded/fail-safe
            self._state.status = ControllerStatus.DEGRADED
        elif fail_safe_count == len(zone_statuses):
            # ALL zones are in fail-safe (no normal, no initializing, no degraded)
            self._state.status = ControllerStatus.FAIL_SAFE
        else:
            # Mix of degraded and fail-safe, but no normal or initializing
            self._state.status = ControllerStatus.DEGRADED

    def get_zone_state(self, zone_id: str) -> ZoneState:
        """Get the state of a specific zone. Raises KeyError if zone_id is invalid."""
        return self._zones[zone_id].state

    def get_zone_runtime(self, zone_id: str) -> ZoneRuntime:
        """Get runtime data for a specific zone. Raises KeyError if zone_id invalid."""
        return self._zones[zone_id]

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

    def set_outdoor_temp(self, outdoor_temp: float | None) -> None:
        """
        Set outdoor temperature and recalculate supply target.

        Called once per update cycle, before zone evaluation.

        Args:
            outdoor_temp: Current outdoor temperature, or None if unavailable.

        """
        self._state.outdoor_temp = outdoor_temp
        self._state.supply_target_temp = calculate_supply_target(
            self.config.heating_curve, outdoor_temp
        )

    # -------------------------------------------------------------------------
    # Mode-specific evaluation functions
    # -------------------------------------------------------------------------

    def _evaluate_off_mode(self) -> ControllerActions:
        """
        Off mode - no changes whatsoever.

        Returns empty valve actions - no state detection, no changes.
        """
        return ControllerActions()

    def _evaluate_all_on_mode(self) -> ControllerActions:
        """
        All-on mode - all valves open, boiler fires.

        Permanently heating: heat_request=True.
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
            heat_request=True,
        )

    def _evaluate_all_off_mode(self) -> ControllerActions:
        """
        All-off mode - all valves closed, no heating.

        Permanently not heating: heat_request=False.
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
            heat_request=False,
        )

    def _evaluate_flush_mode(self) -> ControllerActions:
        """
        Flush mode - all valves open, circulation only (no boiler firing).

        Permanently not heating: heat_request=False.
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
            heat_request=False,
        )

    def _evaluate_cycle_mode(self, now: datetime) -> ControllerActions:
        """
        Cycle mode - rotate through zones by hour, circulation only.

        Same as flush mode but one zone at a time on an 8-hour rotation.
        Hour 0: all closed (rest hour)
        Hours 1-7: zones open sequentially

        Permanently not heating: heat_request=False.
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
            heat_request=False,
        )

    def _evaluate_heat_mode(self, now: datetime) -> ControllerActions:
        """
        Heat mode - quota-based scheduling with flush circuit logic.

        Uses PID-based quota scheduling for regular zones, then evaluates
        flush circuits based on whether any regular zones are running.

        Returns raw computed values; the coordinator handles change detection.
        """
        valve_actions: dict[str, ZoneAction] = {}

        # Phase 1: Evaluate regular zones first using quota-based scheduling
        for zone_id, runtime in self._zones.items():
            if runtime.config.circuit_type == CircuitType.REGULAR:
                valve_actions[zone_id] = evaluate_zone(
                    runtime.state, self._state, self.config.timing
                )

        # Phase 2: Compute flush_request based on regular zone actions
        any_regular_on = any(
            action in {ZoneAction.TURN_ON, ZoneAction.STAY_ON}
            for action in valve_actions.values()
        )
        flush_request = compute_flush_request(
            flush_enabled=self._state.flush_enabled,
            dhw_active=self._state.dhw_active,
            flush_until=self._state.flush_until,
            any_regular_on=any_regular_on,
            now=now,
        )

        # Phase 3: Evaluate flush zones with explicit flush_request parameter
        for zone_id, runtime in self._zones.items():
            if runtime.config.circuit_type == CircuitType.FLUSH:
                valve_actions[zone_id] = evaluate_zone(
                    runtime.state,
                    self._state,
                    self.config.timing,
                    flush_request=flush_request,
                )

        # Aggregate heat request from per-zone decisions
        remaining_durations = {
            zone_id: rt.state.remaining_duration
            for zone_id, rt in self._zones.items()
            if rt.state.flow
        }
        heat_request = any(
            rd > self.config.timing.closing_warning_duration
            for rd in remaining_durations.values()
        )

        return ControllerActions(
            valve_actions=valve_actions,
            heat_request=heat_request,
            flush_request=flush_request,
        )

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
        if mode == OperationMode.HEAT:
            return self._evaluate_heat_mode(now)
        if mode == OperationMode.FLUSH:
            return self._evaluate_flush_mode()
        if mode == OperationMode.CYCLE:
            return self._evaluate_cycle_mode(now)
        if mode == OperationMode.ALL_ON:
            return self._evaluate_all_on_mode()
        if mode == OperationMode.ALL_OFF:
            return self._evaluate_all_off_mode()
        return self._evaluate_off_mode()

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

        if mode == OperationMode.OFF:
            return None

        if mode in (OperationMode.FLUSH, OperationMode.ALL_OFF):
            return SummerMode.SUMMER

        if mode == OperationMode.ALL_ON:
            return SummerMode.WINTER

        # Heat and cycle modes depend on heat request
        return SummerMode.WINTER if heat_request else SummerMode.SUMMER

    @property
    def zone_ids(self) -> list[str]:
        """Get list of all zone IDs."""
        return list(self._zones.keys())

    @property
    def zone_runtimes(self) -> list[ZoneRuntime]:
        """Get list of all zone runtimes."""
        return list(self._zones.values())
