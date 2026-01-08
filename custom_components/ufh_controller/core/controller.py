"""
Controller logic for UFH Controller.

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
    ) -> float:
        """
        Update the PID controller for a zone.

        Args:
            zone_id: Zone identifier.
            current: Current temperature reading, or None if unavailable.
            dt: Time delta since last update in seconds.

        Returns:
            The new duty cycle (0-100), or 0 if zone not found or temp unavailable.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return 0.0

        runtime.state.current = current

        if current is None:
            # No temperature reading - maintain last duty cycle
            return runtime.state.duty_cycle

        pid_output = runtime.pid.update(
            setpoint=runtime.state.setpoint,
            current=current,
            dt=dt,
        )

        # Update zone state with PID output
        runtime.state.error = pid_output.error
        runtime.state.p_term = pid_output.p_term
        runtime.state.i_term = pid_output.i_term
        runtime.state.d_term = pid_output.d_term
        runtime.state.duty_cycle = pid_output.duty_cycle

        return pid_output.duty_cycle

    def update_zone_historical(  # noqa: PLR0913
        self,
        zone_id: str,
        *,
        duty_cycle_avg: float,
        period_state_avg: float,
        open_state_avg: float,
        window_open_avg: float,
        elapsed_time: float,
    ) -> None:
        """
        Update zone historical averages from Recorder queries.

        Args:
            zone_id: Zone identifier.
            duty_cycle_avg: Average duty cycle over window.
            period_state_avg: Average valve state since observation start.
            open_state_avg: Average valve state for open detection.
            window_open_avg: Average window open state.
            elapsed_time: Actual elapsed time since observation start in seconds.

        """
        runtime = self._zones.get(zone_id)
        if runtime is None:
            return

        runtime.state.duty_cycle_avg = duty_cycle_avg
        runtime.state.period_state_avg = period_state_avg
        runtime.state.open_state_avg = open_state_avg
        runtime.state.window_open_avg = window_open_avg

        # Calculate used and requested durations
        period = self.config.timing.observation_period
        runtime.state.used_duration = period_state_avg * elapsed_time
        # requested_duration uses full observation period
        runtime.state.requested_duration = calculate_requested_duration(
            runtime.state.duty_cycle,
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
            # Update valve state based on action
            runtime.state.valve_on = action in (ZoneAction.TURN_ON, ZoneAction.STAY_ON)

        return actions

    def _evaluate_single_zone(
        self,
        zone_id: str,
        runtime: ZoneRuntime,
    ) -> ZoneAction:
        """Evaluate a single zone based on current mode."""
        mode = self._state.mode
        valve_on = runtime.state.valve_on

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
        valve_on = runtime.state.valve_on

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
            "winter" for heating, "summer" for no heating, or None if not applicable.

        """
        if self.config.summer_mode_entity is None:
            return None

        mode = self._state.mode

        if mode == "disabled":
            return None

        if mode in ("flush", "all_off"):
            return "summer"

        if mode == "all_on":
            return "winter"

        # Auto and cycle modes depend on heat request
        return "winter" if heat_request else "summer"

    @property
    def zone_ids(self) -> list[str]:
        """Get list of all zone IDs."""
        return list(self._zones.keys())
