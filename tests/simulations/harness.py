"""Simulation harness replacing the HA coordinator for pure-Python testing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from custom_components.ufh_controller.const import (
    ControllerStatus,
    ValveState,
)
from custom_components.ufh_controller.core.zone import ZoneAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from custom_components.ufh_controller.core.controller import HeatingController

    from .room_model import RoomModel

# Valve position threshold — matches DEFAULT_VALVE_OPEN_THRESHOLD
_VALVE_OPEN_THRESHOLD = 0.85


@dataclass(frozen=True)
class SimulationEntry:
    """Per-zone-per-step snapshot for analysis."""

    time: float  # seconds since simulation start
    zone_id: str
    room_temp: float
    setpoint: float
    duty_cycle: float
    integral: float
    valve_on: bool
    flow: bool
    used_duration: float
    requested_duration: float
    heat_request: bool | None


class SimulationLog:
    """Wrap a list of SimulationEntry with filter helpers."""

    def __init__(self) -> None:
        """Initialize an empty log."""
        self._entries: list[SimulationEntry] = []

    def append(self, entry: SimulationEntry) -> None:
        """Append an entry to the log."""
        self._entries.append(entry)

    def zone_entries(self, zone_id: str) -> list[SimulationEntry]:
        """Return all entries for a given zone."""
        return [e for e in self._entries if e.zone_id == zone_id]

    def zone_entries_after(
        self, zone_id: str, after_seconds: float
    ) -> list[SimulationEntry]:
        """Return entries for a zone after a given time."""
        return [
            e for e in self._entries if e.zone_id == zone_id and e.time >= after_seconds
        ]

    @property
    def entries(self) -> list[SimulationEntry]:
        """Return a copy of all entries."""
        return list(self._entries)


class SimulationHarness:
    """
    Drive a HeatingController with room thermal models.

    Replicates the coordinator update sequence without any HA dependencies.
    """

    def __init__(
        self,
        controller: HeatingController,
        rooms: dict[str, RoomModel],
        *,
        dt: float = 60.0,
        outdoor_temp: float | None = None,
        dhw_schedule: Callable[[float], bool] | None = None,
        window_schedules: dict[str, Callable[[float], bool]] | None = None,
        valve_open_time: float = 180.0,
        valve_close_time: float = 90.0,
    ) -> None:
        """
        Initialize the simulation harness.

        Args:
            controller: HeatingController instance to drive.
            rooms: Map of zone_id to RoomModel.
            dt: Time step in seconds.
            outdoor_temp: Outdoor temperature for heating curve.
            dhw_schedule: Callable returning DHW active state for a given time.
            window_schedules: Map of zone_id to window open schedule.
            valve_open_time: Seconds for valve to fully open.
            valve_close_time: Seconds for valve to fully close.

        """
        self.controller = controller
        self.rooms = rooms
        self.dt = dt
        self.outdoor_temp = outdoor_temp
        self.dhw_schedule = dhw_schedule
        self.window_schedules = window_schedules or {}
        self.valve_open_time = valve_open_time
        self.valve_close_time = valve_close_time

        # Valve position per zone: 0.0 (closed) to 1.0 (open)
        self._valve_position: dict[str, float] = dict.fromkeys(rooms, 0.0)

    def run(
        self,
        duration: float,
        *,
        start_time: datetime | None = None,
        mutations: list[tuple[float, Callable[[SimulationHarness], None]]]
        | None = None,
    ) -> SimulationLog:
        """
        Run the simulation for the given duration in seconds.

        Args:
            duration: Total simulation time in seconds.
            start_time: Start datetime (defaults to controller's started_at).
            mutations: List of (time_seconds, callback) to apply mid-simulation.

        Returns:
            SimulationLog with per-zone-per-step snapshots.

        """
        log = SimulationLog()
        now = start_time or self.controller.state.started_at
        steps = int(duration / self.dt)
        sorted_mutations = sorted(mutations or [], key=lambda m: m[0])
        mutation_idx = 0
        elapsed = 0.0

        for _ in range(steps):
            # Apply any mutations due at this time
            while mutation_idx < len(sorted_mutations):
                mt, mfn = sorted_mutations[mutation_idx]
                if mt <= elapsed:
                    mfn(self)
                    mutation_idx += 1
                else:
                    break

            self._step(now, elapsed, log)

            elapsed += self.dt
            now += timedelta(seconds=self.dt)

        return log

    def _step(self, now: datetime, elapsed: float, log: SimulationLog) -> None:
        """Execute one simulation step."""
        dt = self.dt
        controller = self.controller
        timing = controller.config.timing

        # Phase 1: Observation period & DHW
        controller.handle_observation_period_transition(now)

        if self.dhw_schedule is not None:
            controller.update_dhw_state(dhw_active=self.dhw_schedule(elapsed), now=now)

        # Phase 2: Outdoor temp
        controller.set_outdoor_temp(self.outdoor_temp)

        # Phase 3: Per-zone updates
        for zone_id in controller.zone_ids:
            runtime = controller.get_zone_runtime(zone_id)
            room = self.rooms[zone_id]

            # Update valve position ramp based on current valve command
            self._ramp_valve(zone_id, runtime.state.valve_state, dt)
            position = self._valve_position[zone_id]

            # Update temperature from room model (no EMA lag when tau=0)
            runtime.update_temperature(room.temp, dt)

            # Update PID
            runtime.update_pid(dt, controller.mode)

            # Update requested duration
            runtime.update_requested_duration(timing.observation_period)

            # Update historical (valve position → flow detection)
            window = False
            if zone_id in self.window_schedules:
                window = self.window_schedules[zone_id](elapsed)
            runtime.update_historical(valve_position=position, window=window)

            # Supply coefficient — no supply sensor in simulations
            runtime.update_supply_coefficient(supply_temp=None, supply_target_temp=40.0)

            # Derive heat state
            runtime.update_heat_state()

            # Accumulate used duration
            runtime.update_used_duration(dt)

            # Update failure state — always successful in simulation
            runtime.update_failure_state(
                now, temp_unavailable=False, valve_unavailable=False
            )

        # Phase 4: Status update
        controller.update_status(now=now, has_pending_entities=False)

        # Skip evaluation during init/fail-safe, but keep room physics running
        status = controller.status
        if status in (
            ControllerStatus.INITIALIZING,
            ControllerStatus.FAIL_SAFE,
        ):
            for room in self.rooms.values():
                room.step(dt, heating_on=False)
            self._log_step(elapsed, log)
            return

        # Phase 5: Evaluate and execute
        actions = controller.evaluate(now=now)

        # Execute valve actions — update valve_state for next step's ramp
        for zone_id, action in actions.valve_actions.items():
            runtime = controller.get_zone_runtime(zone_id)
            if action in (ZoneAction.TURN_ON, ZoneAction.STAY_ON):
                runtime.state.valve_state = ValveState.ON
            else:
                runtime.state.valve_state = ValveState.OFF

        # Store pump and heat request
        controller.state.pump_request = actions.pump_request
        controller.state.heat_request = actions.heat_request

        # Advance room models — heat only when valve sufficiently open
        for zone_id, room in self.rooms.items():
            position = self._valve_position[zone_id]
            room.step(dt, position >= _VALVE_OPEN_THRESHOLD)

        self._log_step(elapsed, log)

    def _ramp_valve(self, zone_id: str, valve_state: ValveState, dt: float) -> None:
        """Ramp valve position based on command state."""
        pos = self._valve_position[zone_id]
        if valve_state == ValveState.ON:
            pos = min(1.0, pos + dt / self.valve_open_time)
        else:
            pos = max(0.0, pos - dt / self.valve_close_time)
        self._valve_position[zone_id] = pos

    def _log_step(self, elapsed: float, log: SimulationLog) -> None:
        """Log a snapshot for each zone."""
        controller = self.controller
        for zone_id in controller.zone_ids:
            runtime = controller.get_zone_runtime(zone_id)
            state = runtime.state
            pid_state = runtime.pid.state

            log.append(
                SimulationEntry(
                    time=elapsed,
                    zone_id=zone_id,
                    room_temp=self.rooms[zone_id].temp,
                    setpoint=state.setpoint,
                    duty_cycle=pid_state.duty_cycle if pid_state else 0.0,
                    integral=pid_state.integral if pid_state else 0.0,
                    valve_on=state.valve_state == ValveState.ON,
                    flow=state.flow,
                    used_duration=state.used_duration,
                    requested_duration=state.requested_duration,
                    heat_request=controller.state.heat_request,
                )
            )
