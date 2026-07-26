"""
Controller logic for Underfloor Heating Controller.

This module provides the main HeatingController class that orchestrates
zone control, operation modes, and heat request aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from custom_components.ufh_controller.const import (
    DEFAULT_CYCLE_MODE_HOURS,
    DEFAULT_DHW_PRIORITY,
    FAIL_SAFE_TIMEOUT,
    INITIALIZING_TIMEOUT,
    ControllerStatus,
    DHWPriority,
    OperationMode,
    SummerMode,
    TimingConfig,
    ValveState,
    ZoneStatus,
)

from .heating_curve import HeatingCurveConfig, calculate_supply_target
from .history import get_observation_start
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
    pump_request: bool | None = None
    heat_request: bool | None = None
    flush_enabled: bool = False
    dhw_active: bool = False
    dhw_priority: DHWPriority = DEFAULT_DHW_PRIORITY
    dhw_sensor_available: bool = True
    dhw_sensor_fault: bool = False
    dhw_sensor_fault_since: datetime | None = None
    dhw_block: bool = False
    dhw_block_until: datetime | None = None
    flush_until: datetime | None = None
    flush_request: bool = False
    zones: dict[str, ZoneState] = field(default_factory=dict)
    outdoor_temp: float | None = None
    supply_target_temp: float | None = None
    last_force_update: datetime | None = None


@dataclass
class ControllerConfig:
    """Configuration for the heating controller."""

    controller_id: str
    name: str
    pump_request_entity: str | None = None
    heat_request_entity: str | None = None
    dhw_active_entity: str | None = None
    dhw_priority: DHWPriority = DEFAULT_DHW_PRIORITY
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
    pump_request: bool | None = None
    heat_request: bool | None = None
    flush_request: bool = False


def is_dhw_sensor_faulted(
    *,
    sensor_available: bool,
    priority: DHWPriority,
) -> bool:
    """
    Decide whether an unreadable DHW sensor is a fault.

    A sensor reading unavailable or unknown carries no information at all.
    Under absolute priority that is not a state to be inferred: the setting
    exists because we must be certain DHW is not charging before opening a
    circuit, and neither "assume off" nor "assume the last known value" can
    provide that certainty. It is treated as a fault instead.

    Parallel and partial keep the historical behaviour of resolving an
    unreadable sensor to "off", where the cost is comfort rather than damage.

    Args:
        sensor_available: Whether the DHW sensor reported a usable state.
        priority: Configured DHW priority level.

    Returns:
        True if the unreadable sensor should be treated as a fault.

    """
    return not sensor_available and priority == DHWPriority.ABSOLUTE


def compute_flush_request(  # noqa: PLR0913
    *,
    flush_enabled: bool,
    dhw_active: bool,
    dhw_block: bool,
    flush_until: datetime | None,
    any_regular_on: bool,
    now: datetime,
) -> bool:
    """
    Compute whether flush circuits should activate.

    Flush circuits activate when:
    - flush_enabled is True (user has enabled the feature)
    - DHW is NOT currently active
    - Absolute DHW priority is NOT holding circuits closed
    - Post-DHW timer is active
    - No regular circuits are currently ON

    Latent heat capture and absolute DHW priority are opposing answers to the
    same question: what to do with the water left in the primary when DHW
    finishes. The block wins, which makes the two mutually exclusive by
    construction rather than merely by evaluation order.

    Args:
        flush_enabled: User toggle for flush feature.
        dhw_active: Whether DHW is currently heating.
        dhw_block: Whether absolute DHW priority is holding circuits closed.
        flush_until: Post-DHW timer expiration, or None.
        any_regular_on: Whether any regular zones have valves ON.
        now: Current time for timer comparison.

    Returns:
        True if flush circuits should activate.

    """
    if not flush_enabled:
        return False

    if dhw_active or dhw_block:
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
        self._state = ControllerState(
            started_at=started_at,
            mode=OperationMode.HEAT,
            dhw_priority=config.dhw_priority,
        )
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
            self._apply_dhw_fault_status(now)
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

        self._apply_dhw_fault_status(now)

    def _apply_dhw_fault_status(self, now: datetime) -> None:
        """
        Raise the controller status while the DHW sensor is faulted.

        Two stages, matching how zone failures already escalate. The block
        applied in update_dhw_state is the protective half and is immediate;
        this is the reporting half. Escalation to fail-safe is deferred by
        FAIL_SAFE_TIMEOUT because the valves are already shut, so it adds no
        protection - it signals a persistent fault and hands the boiler back
        its own thermostats.

        Applied after zone aggregation so it cannot be overwritten, and after
        the INITIALIZING deferral so a sensor that has not loaded yet during
        startup does not trip it.
        """
        if not self._state.dhw_sensor_fault:
            return

        since = self._state.dhw_sensor_fault_since
        if since is not None and (now - since).total_seconds() > FAIL_SAFE_TIMEOUT:
            self._state.status = ControllerStatus.FAIL_SAFE
        elif self._state.status != ControllerStatus.FAIL_SAFE:
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
            pump_request=True,
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
            pump_request=False,
            heat_request=False,
        )

    def _evaluate_flush_mode(self) -> ControllerActions:
        """
        Flush mode - all valves open, circulation only (no boiler firing).

        Permanently not heating: heat_request=False. Suspended while absolute
        DHW priority holds the circuits closed; the mode itself is retained and
        resumes once the block clears.
        """
        if self._state.dhw_block:
            return self._evaluate_all_off_mode()

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
            pump_request=True,
            heat_request=False,
        )

    def _evaluate_cycle_mode(self, now: datetime) -> ControllerActions:
        """
        Cycle mode - rotate through zones by hour, circulation only.

        Same as flush mode but one zone at a time on an 8-hour rotation.
        Hour 0: all closed (rest hour)
        Hours 1-7: zones open sequentially

        Permanently not heating: heat_request=False. Suspended while absolute
        DHW priority holds the circuits closed; the rotation is retained and
        resumes once the block clears.
        """
        if self._state.dhw_block:
            return self._evaluate_all_off_mode()

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

        pump_request = any(rt.state.flow for rt in self._zones.values())
        return ControllerActions(
            valve_actions=valve_actions,
            pump_request=pump_request,
            heat_request=False,
        )

    def _evaluate_heat_mode(self, now: datetime) -> ControllerActions:
        """
        Heat mode - quota-based scheduling with flush circuit logic.

        Uses PID-based quota scheduling for regular zones, then evaluates
        flush circuits based on whether any regular zones are running.

        Both the heat and pump requests are gated on dhw_block. Thermal
        actuators need minutes to close, so a circuit still reports flow at the
        instant DHW asserts; without the gate the controller would ask the
        boiler to fire mid-charge and keep an independent circulation pump
        pushing cylinder-temperature water through the closing circuit. Since
        pump_request_entity drives a pump the controller owns, stopping it is
        the one part of that exposure window software can actually shorten.

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
            dhw_block=self._state.dhw_block,
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

        # Pump request: any zone with confirmed flow, unless DHW holds us closed
        pump_request = not self._state.dhw_block and any(
            rt.state.flow for rt in self._zones.values()
        )

        # Aggregate heat request from per-zone decisions, gated on pump and DHW
        remaining_durations = {
            zone_id: rt.state.remaining_duration
            for zone_id, rt in self._zones.items()
            if rt.state.flow
        }
        heat_request = (
            not self._state.dhw_block
            and pump_request
            and any(
                rd > self.config.timing.closing_warning_duration
                for rd in remaining_durations.values()
            )
        )

        return ControllerActions(
            valve_actions=valve_actions,
            pump_request=pump_request,
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
            actions = self._evaluate_heat_mode(now)
        elif mode == OperationMode.FLUSH:
            actions = self._evaluate_flush_mode()
        elif mode == OperationMode.CYCLE:
            actions = self._evaluate_cycle_mode(now)
        elif mode == OperationMode.ALL_ON:
            actions = self._evaluate_all_on_mode()
        elif mode == OperationMode.ALL_OFF:
            actions = self._evaluate_all_off_mode()
        else:
            actions = self._evaluate_off_mode()

        # Safety net: heat request requires pump request
        if not actions.pump_request and actions.heat_request:
            actions.heat_request = False

        return actions

    def get_summer_mode_value(
        self, *, heat_request: bool, fail_safe: bool = False
    ) -> SummerMode | None:
        """
        Determine the summer mode value for the boiler.

        Args:
            heat_request: Current heat request state.
            fail_safe: Whether zone control has been lost (any zone in
                fail-safe). Only heat mode delegates to the boiler.

        Returns:
            SummerMode.AUTO to hand control to the boiler, SummerMode.WINTER
            for heating, SummerMode.SUMMER for no heating, or None if not
            applicable.

        """
        if self.config.summer_mode_entity is None:
            return None

        mode = self._state.mode

        if mode == OperationMode.OFF:
            return None

        # Explicit modes state user intent; a zone failure must not override it
        if mode in (OperationMode.FLUSH, OperationMode.CYCLE, OperationMode.ALL_OFF):
            return SummerMode.SUMMER

        if mode == OperationMode.ALL_ON:
            return SummerMode.WINTER

        # Heat is the only automatic mode: delegate so fallback thermostats get supply
        if fail_safe:
            return SummerMode.AUTO

        return SummerMode.WINTER if heat_request else SummerMode.SUMMER

    def _apply_dhw_sensor_fault(self, now: datetime) -> None:
        """
        Hold everything still while the DHW sensor cannot be read.

        No edge detection and no timer changes: an unreadable sensor gives no
        information to detect edges from, and inventing one would either arm
        the recovery hold-off from a charge that has not ended or release a
        hold-off that should still be running. Circuits are blocked outright
        instead, and the fault clock starts so a sustained outage can escalate.
        """
        self._state.dhw_sensor_available = False
        self._state.dhw_block = True
        if not self._state.dhw_sensor_fault:
            self._state.dhw_sensor_fault = True
            self._state.dhw_sensor_fault_since = now

    def update_dhw_state(
        self, *, dhw_active: bool, now: datetime, sensor_available: bool = True
    ) -> None:
        """
        Update DHW state and manage the block and post-DHW flush timers.

        Detects transitions:
        - ON→OFF: arms the recovery hold-off and starts the post-flush timer if
          flush enabled and duration > 0
        - OFF→ON: clears flush_until timer

        Recomputes dhw_block on every call so the hold-off expires on time.

        Args:
            dhw_active: Current DHW active state, already resolved against
                sensor availability by resolve_dhw_active.
            now: Current time for timer calculation.
            sensor_available: Whether the DHW sensor reported a usable state,
                recorded for diagnostics.

        """
        self._state.dhw_priority = self.config.dhw_priority
        absolute = self.config.dhw_priority == DHWPriority.ABSOLUTE
        recovery = self.config.timing.dhw_recovery_time

        if is_dhw_sensor_faulted(
            sensor_available=sensor_available, priority=self.config.dhw_priority
        ):
            self._apply_dhw_sensor_fault(now)
            return

        self._state.dhw_sensor_available = sensor_available
        self._state.dhw_sensor_fault = False
        self._state.dhw_sensor_fault_since = None

        # Detect DHW OFF transition (was on, now off)
        if self._state.dhw_active and not dhw_active:
            # Safety timer, armed regardless of the flush feature
            self._state.dhw_block_until = now + timedelta(seconds=recovery)

            flush_duration = self.config.timing.flush_duration
            if flush_duration > 0 and self._state.flush_enabled:
                # Flush opens after the hold-off under absolute, at once otherwise
                offset = recovery if absolute else 0
                self._state.flush_until = now + timedelta(
                    seconds=offset + flush_duration
                )

        # Clear flush_until when DHW starts
        if dhw_active and not self._state.dhw_active:
            self._state.flush_until = None

        # Drop an expired deadline so it stops being reported as pending
        if (
            self._state.dhw_block_until is not None
            and now >= self._state.dhw_block_until
        ):
            self._state.dhw_block_until = None

        self._state.dhw_active = dhw_active
        self._state.dhw_block = absolute and (
            dhw_active or self._state.dhw_block_until is not None
        )

    def handle_observation_period_transition(self, now: datetime) -> bool:
        """
        Update observation period state and return whether a new period started.

        This method:
        1. Updates observation_start and period_elapsed
        2. Detects if we've transitioned to a new observation period
        3. Resets used_duration for all zones on period transition
        4. Updates last_force_update timestamp

        Args:
            now: Current time.

        Returns:
            True if a new observation period started (force update needed).

        """
        timing = self.config.timing
        self._state.observation_start = get_observation_start(
            now, timing.observation_period
        )
        self._state.period_elapsed = (
            now - self._state.observation_start
        ).total_seconds()

        new_period = (
            self._state.last_force_update is None
            or self._state.last_force_update < self._state.observation_start
        )

        if new_period:
            for runtime in self._zones.values():
                runtime.reset_used_duration()
            self._state.last_force_update = now

        return new_period

    @property
    def any_zone_in_fail_safe(self) -> bool:
        """Check if any zone is in fail-safe mode."""
        return any(
            rt.state.zone_status == ZoneStatus.FAIL_SAFE for rt in self._zones.values()
        )

    @property
    def zone_ids(self) -> list[str]:
        """Get list of all zone IDs."""
        return list(self._zones.keys())

    @property
    def zone_runtimes(self) -> list[ZoneRuntime]:
        """Get list of all zone runtimes."""
        return list(self._zones.values())
