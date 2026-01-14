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
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TEMP_EMA_TIME_CONSTANT,
    SummerMode,
    ValveState,
)

from .pid import PIDController
from .zone import (
    CircuitType,
    ControllerState,
    TimingParams,
    ZoneAction,
    ZoneState,
    aggregate_heat_request,
    calculate_requested_duration,
    evaluate_zone,
)


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
class ZoneRuntime:
    """Runtime data for a zone including PID controller and state."""

    config: ZoneConfig
    pid: PIDController
    state: ZoneState
    last_update: datetime | None = None


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

        # Clamp setpoint to configured limits
        clamped = max(
            runtime.config.setpoint_min,
            min(runtime.config.setpoint_max, setpoint),
        )
        runtime.state.setpoint = clamped
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
        runtime.state.enabled = enabled
        return True

    def update_zone_pid(
        self,
        zone_id: str,
        current: float | None,
        dt: float,
    ) -> float | None:
        """
        Update the PID controller for a zone.

        PID integration is paused (no update called) when:
        - Temperature reading is unavailable
        - Controller mode is not 'auto' (PID only meaningful in auto mode)
        - Zone is disabled
        - Window was open recently (within blocking period + delay)

        This prevents integral windup during blocked periods while allowing
        the valve to remain open at the last calculated duty cycle.

        Args:
            zone_id: Zone identifier.
            current: Current temperature reading, or None if unavailable.
            dt: Time delta since last update in seconds.

        Returns:
            The new duty cycle (0-100), None if not yet calculated, or 0 if zone
            not found.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return 0.0

        runtime.state.current = current

        if current is None:
            # No temperature reading - maintain last duty cycle, pause integration
            return runtime.pid.state.duty_cycle if runtime.pid.state else None

        # Check if PID should be paused (prevent integral windup)
        if self._should_pause_pid(runtime):
            return runtime.pid.state.duty_cycle if runtime.pid.state else None

        pid_state = runtime.pid.update(
            setpoint=runtime.state.setpoint,
            current=current,
            dt=dt,
        )

        return pid_state.duty_cycle

    def _should_pause_pid(self, runtime: ZoneRuntime) -> bool:
        """
        Check if PID integration should be paused for a zone.

        PID is paused when:
        - Controller mode is not 'auto' (other modes don't use PID control)
        - Zone is disabled
        - Window was open recently (within blocking period)

        Args:
            runtime: Zone runtime data.

        Returns:
            True if PID should be paused, False otherwise.

        """
        # Only auto mode uses PID-based control
        if self._state.mode != "auto":
            return True

        # Disabled zones shouldn't accumulate integral
        if not runtime.state.enabled:
            return True

        # Window was open recently - pause PID to let temperature stabilize
        return runtime.state.window_recently_open

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

        runtime.state.period_state_avg = period_state_avg
        runtime.state.open_state_avg = open_state_avg
        runtime.state.window_recently_open = window_recently_open

        # Calculate used and requested durations
        period = self.config.timing.observation_period
        runtime.state.used_duration = period_state_avg * elapsed_time
        # requested_duration uses full observation period
        duty_cycle = runtime.pid.state.duty_cycle if runtime.pid.state else 0.0
        runtime.state.requested_duration = calculate_requested_duration(
            duty_cycle,
            period,
        )

    def evaluate_zones(self) -> dict[str, ZoneAction]:
        """
        Evaluate all zones and determine valve actions.

        Handles operation modes and per-zone decision logic.

        Returns:
            Dictionary mapping zone IDs to their actions.

        """
        actions: dict[str, ZoneAction] = {}

        # Build current controller state for decision logic
        self._state.zones = {zid: zr.state for zid, zr in self._zones.items()}

        for zone_id, runtime in self._zones.items():
            action = self._evaluate_single_zone(zone_id, runtime)
            actions[zone_id] = action
            # Update expected valve state based on action
            if action in (ZoneAction.TURN_ON, ZoneAction.STAY_ON):
                runtime.state.valve_state = ValveState.ON
            else:
                runtime.state.valve_state = ValveState.OFF

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
