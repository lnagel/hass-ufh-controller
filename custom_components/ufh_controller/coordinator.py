"""DataUpdateCoordinator for Underfloor Heating Controller."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from sqlalchemy.exc import SQLAlchemyError

from .const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DEFAULT_VALVE_OPEN_THRESHOLD,
    DOMAIN,
    FAIL_SAFE_TIMEOUT,
    LOGGER,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
    ControllerStatus,
    OperationMode,
    SummerMode,
    ValveState,
    ZoneStatus,
)
from .core import (
    ControllerConfig,
    HeatingController,
    TimingParams,
    ZoneAction,
    ZoneConfig,
    get_observation_start,
    get_state_average,
    get_valve_open_window,
    get_window_open_average,
)
from .core.zone import CircuitType

# Storage constants
STORAGE_VERSION = 1
STORAGE_KEY = "ufh_controller"


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import UFHControllerConfigEntry


class UFHControllerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Underfloor Heating Controller data."""

    config_entry: UFHControllerConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: UFHControllerConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        # Build controller first to get timing config
        self._controller = self._build_controller(entry)
        self._loop_interval = self._controller.config.timing.controller_loop_interval

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._loop_interval),
        )
        self.config_entry = entry
        self._last_update: datetime | None = None

        # Storage for crash resilience
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry.entry_id}",
        )
        self._state_restored: bool = False

        # Track preset modes per zone (not part of core controller state)
        self._zone_presets: dict[str, str | None] = {}

        # Controller status (derived from zone statuses)
        self._status: ControllerStatus = ControllerStatus.INITIALIZING

    def _build_controller(self, entry: UFHControllerConfigEntry) -> HeatingController:
        """Build HeatingController from config entry."""
        data = entry.data

        # Get timing from controller subentry, fall back to options for migration
        timing_opts: dict[str, Any] = {}
        for subentry in entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
                timing_opts = subentry.data.get("timing", {})
                break
        if not timing_opts:
            # Fallback to options for backwards compatibility
            timing_opts = entry.options.get("timing", {})

        timing = TimingParams(
            observation_period=timing_opts.get(
                "observation_period", DEFAULT_TIMING["observation_period"]
            ),
            min_run_time=timing_opts.get(
                "min_run_time", DEFAULT_TIMING["min_run_time"]
            ),
            valve_open_time=timing_opts.get(
                "valve_open_time", DEFAULT_TIMING["valve_open_time"]
            ),
            closing_warning_duration=timing_opts.get(
                "closing_warning_duration", DEFAULT_TIMING["closing_warning_duration"]
            ),
            window_block_time=timing_opts.get(
                "window_block_time", DEFAULT_TIMING["window_block_time"]
            ),
            controller_loop_interval=timing_opts.get(
                "controller_loop_interval", DEFAULT_TIMING["controller_loop_interval"]
            ),
        )

        # Build zones from subentries
        zones: list[ZoneConfig] = []
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_ZONE:
                continue
            zone_data = subentry.data
            pid_opts = zone_data.get("pid", {})
            setpoint_opts = zone_data.get("setpoint", {})

            zones.append(
                ZoneConfig(
                    zone_id=zone_data["id"],
                    name=zone_data["name"],
                    temp_sensor=zone_data["temp_sensor"],
                    valve_switch=zone_data["valve_switch"],
                    circuit_type=CircuitType(zone_data.get("circuit_type", "regular")),
                    window_sensors=zone_data.get("window_sensors", []),
                    setpoint_min=setpoint_opts.get("min", DEFAULT_SETPOINT["min"]),
                    setpoint_max=setpoint_opts.get("max", DEFAULT_SETPOINT["max"]),
                    setpoint_default=setpoint_opts.get(
                        "default", DEFAULT_SETPOINT["default"]
                    ),
                    kp=pid_opts.get("kp", DEFAULT_PID["kp"]),
                    ki=pid_opts.get("ki", DEFAULT_PID["ki"]),
                    kd=pid_opts.get("kd", DEFAULT_PID["kd"]),
                    integral_min=pid_opts.get(
                        "integral_min", DEFAULT_PID["integral_min"]
                    ),
                    integral_max=pid_opts.get(
                        "integral_max", DEFAULT_PID["integral_max"]
                    ),
                )
            )

        config = ControllerConfig(
            controller_id=data["controller_id"],
            name=data["name"],
            heat_request_entity=data.get("heat_request_entity"),
            dhw_active_entity=data.get("dhw_active_entity"),
            circulation_entity=data.get("circulation_entity"),
            summer_mode_entity=data.get("summer_mode_entity"),
            timing=timing,
            zones=zones,
        )

        return HeatingController(config)

    @property
    def controller(self) -> HeatingController:
        """Return the heating controller."""
        return self._controller

    async def async_load_stored_state(self) -> None:
        """Load state from storage (fallback if RestoreEntity fails)."""
        if self._state_restored:
            return

        stored_data = await self._store.async_load()
        if stored_data is None:
            self._state_restored = True
            return

        # Restore controller mode
        if "controller_mode" in stored_data:
            stored_mode = stored_data["controller_mode"]
            if stored_mode in [mode.value for mode in OperationMode]:
                self._controller.mode = stored_mode

        # Restore zone state
        zones_data = stored_data.get("zones", {})
        for zone_id, zone_state in zones_data.items():
            self._restore_zone_state(zone_id, zone_state)

        self._state_restored = True

    def _restore_zone_state(self, zone_id: str, zone_state: dict[str, Any]) -> None:
        """Restore state for a single zone from storage."""
        runtime = self._controller.get_zone_runtime(zone_id)
        if runtime is None:
            return

        # Restore PID integral (only if not yet calculated - i_term is None or 0.0)
        if runtime.state.i_term is None or runtime.state.i_term == 0.0:
            integral = zone_state.get("integral", 0.0)
            last_error = zone_state.get("last_error", 0.0)
            if integral != 0.0:
                runtime.pid.set_integral(integral)
                runtime.pid.set_last_error(last_error)
                runtime.state.i_term = integral

        # Restore setpoint
        if "setpoint" in zone_state:
            stored_setpoint = zone_state["setpoint"]
            if stored_setpoint != runtime.state.setpoint:
                self._controller.set_zone_setpoint(zone_id, stored_setpoint)

        # Restore enabled state
        if "enabled" in zone_state:
            stored_enabled = zone_state["enabled"]
            if stored_enabled != runtime.state.enabled:
                self._controller.set_zone_enabled(zone_id, enabled=stored_enabled)

        # Restore preset mode
        if "preset_mode" in zone_state:
            self._zone_presets[zone_id] = zone_state["preset_mode"]

    async def async_save_state(self) -> None:
        """Save current state to storage."""
        zones_data: dict[str, dict[str, Any]] = {}

        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                zone_data: dict[str, Any] = {
                    "integral": runtime.pid.state.integral,
                    "last_error": runtime.pid.state.last_error,
                    "setpoint": runtime.state.setpoint,
                    "enabled": runtime.state.enabled,
                }
                # Include preset_mode if set
                preset_mode = self._zone_presets.get(zone_id)
                if preset_mode is not None:
                    zone_data["preset_mode"] = preset_mode
                zones_data[zone_id] = zone_data

        data = {
            "version": STORAGE_VERSION,
            "saved_at": datetime.now(UTC).isoformat(),
            "controller_mode": self._controller.mode,
            "zones": zones_data,
        }

        await self._store.async_save(data)

    @property
    def status(self) -> ControllerStatus:
        """Return the current controller operational status."""
        return self._status

    async def _execute_fail_safe_actions(self) -> None:
        """Execute fail-safe mode actions - close all valves and disable heating."""
        # Close all valves
        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime:
                await self._call_switch_service(
                    runtime.config.valve_switch, turn_on=False
                )
                # Update zone state to reflect valve is off
                runtime.state.valve_state = ValveState.OFF

        # Turn off heat request
        await self._execute_heat_request(heat_request=False)

        # Set summer mode to 'auto' to pass control back to the boiler
        summer_entity = self._controller.config.summer_mode_entity
        if summer_entity:
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": summer_entity, "option": SummerMode.AUTO},
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via controller logic."""
        # Load stored state on first run (fallback restoration)
        if not self._state_restored:
            await self.async_load_stored_state()

        now = datetime.now(UTC)
        dt = self._loop_interval
        if self._last_update is not None:
            dt = (now - self._last_update).total_seconds()
        self._last_update = now

        # Skip if no zones configured
        if not self._controller.zone_ids:
            return self._build_state_dict()

        # Update observation start and elapsed time
        timing = self._controller.config.timing
        self._controller.state.observation_start = get_observation_start(
            now, timing.observation_period
        )
        self._controller.state.period_elapsed = (
            now - self._controller.state.observation_start
        ).total_seconds()

        # Check DHW active state
        await self._update_dhw_state()

        # Update each zone (each zone tracks its own failure state)
        for zone_id in self._controller.zone_ids:
            await self._update_zone(zone_id, now, dt)

        # Update controller status from zone statuses
        self._update_controller_status_from_zones()

        # If ALL zones are in fail-safe, execute controller-level fail-safe
        if self._status == ControllerStatus.FAIL_SAFE:
            await self._execute_fail_safe_actions()
            return self._build_state_dict()

        # Evaluate all zones and get actions (zones track their own status)
        actions = self._controller.evaluate_zones()

        # Execute valve actions with zone-level isolation
        await self._execute_valve_actions_with_isolation(actions)

        # Calculate and execute heat request
        heat_request = self._controller.calculate_heat_request()
        await self._execute_heat_request(heat_request=heat_request)

        # Update summer mode if configured (with safety check)
        await self._update_summer_mode(heat_request=heat_request)

        # Save state after every update for crash resilience
        await self.async_save_state()

        return self._build_state_dict()

    async def _update_dhw_state(self) -> None:
        """Update DHW active state from entity."""
        dhw_entity = self._controller.config.dhw_active_entity
        if dhw_entity is None:
            return

        state = self.hass.states.get(dhw_entity)
        self._controller.state.dhw_active = state is not None and state.state == "on"

    def _is_any_window_open(self, window_sensors: list[str]) -> bool:
        """Check if any window sensor is currently in 'on' state."""
        for sensor_id in window_sensors:
            state = self.hass.states.get(sensor_id)
            if state is not None and state.state == "on":
                return True
        return False

    async def _update_zone(
        self,
        zone_id: str,
        now: datetime,
        dt: float,
    ) -> None:
        """
        Update a single zone with current data and historical averages.

        Zone failures are tracked per-zone and don't affect other zones.
        """
        runtime = self._controller.get_zone_runtime(zone_id)
        if runtime is None:
            return  # Zone doesn't exist

        # Read current temperature
        temp_state = self.hass.states.get(runtime.config.temp_sensor)
        current: float | None = None
        temp_unavailable = False
        if temp_state is not None:
            try:
                current = float(temp_state.state)
            except (ValueError, TypeError):
                temp_unavailable = True
                LOGGER.warning(
                    "Invalid temperature state for %s: %s",
                    runtime.config.temp_sensor,
                    temp_state.state,
                )
        else:
            temp_unavailable = True

        # Update PID controller
        self._controller.update_zone_pid(zone_id, current, dt)

        # Query historical data from Recorder
        timing = self._controller.config.timing

        # CRITICAL: Valve state since observation start (for used_duration/quota)
        # If this fails, zone enters degraded state
        period_start = self._controller.state.observation_start
        recorder_failure = False
        try:
            period_state_avg = await get_state_average(
                self.hass,
                runtime.config.valve_switch,
                period_start,
                now,
                on_value="on",
            )
        except SQLAlchemyError:
            recorder_failure = True
            LOGGER.warning(
                "Zone %s: Failed to query period state, zone entering degraded mode",
                zone_id,
                exc_info=True,
            )
            # Use fallback: assume current valve state has been stable
            current_valve_state = self.hass.states.get(runtime.config.valve_switch)
            period_state_avg = (
                1.0
                if ValveState.from_ha_state(current_valve_state) == ValveState.ON
                else 0.0
            )

        # NON-CRITICAL: Valve state for open detection (recent window)
        # Fallback: Use current valve entity state
        valve_start, valve_end = get_valve_open_window(now, timing.valve_open_time)
        try:
            open_state_avg = await get_state_average(
                self.hass,
                runtime.config.valve_switch,
                valve_start,
                valve_end,
                on_value="on",
            )
        except SQLAlchemyError:
            # Fallback to current entity state
            current_valve_state = self.hass.states.get(runtime.config.valve_switch)
            open_state_avg = (
                1.0
                if ValveState.from_ha_state(current_valve_state) == ValveState.ON
                else 0.0
            )
            LOGGER.warning(
                "Recorder query failed for open state, using fallback valve state "
                "for zone %s: %.2f",
                zone_id,
                open_state_avg,
                exc_info=True,
            )

        # NON-CRITICAL: Window sensors average (historical)
        # Fallback: Assume windows are closed
        try:
            window_open_avg = await get_window_open_average(
                self.hass,
                runtime.config.window_sensors,
                period_start,
                now,
            )
        except SQLAlchemyError:
            window_open_avg = 0.0  # Assume closed
            LOGGER.warning(
                "Recorder query failed for window state, assuming closed for zone %s",
                zone_id,
                exc_info=True,
            )

        # Check if any window is currently open
        window_currently_open = self._is_any_window_open(runtime.config.window_sensors)

        # Update zone with historical data
        self._controller.update_zone_historical(
            zone_id,
            period_state_avg=period_state_avg,
            open_state_avg=open_state_avg,
            window_open_avg=window_open_avg,
            window_currently_open=window_currently_open,
            elapsed_time=self._controller.state.period_elapsed,
        )

        # Sync valve state from actual HA entity
        # This ensures we detect when external factors change the valve state
        # (e.g., user toggle, automation, device reset)
        current_valve_state = self.hass.states.get(runtime.config.valve_switch)
        runtime.state.valve_state = ValveState.from_ha_state(current_valve_state)

        # Log if valve entity is unavailable or unknown
        if runtime.state.valve_state == ValveState.UNAVAILABLE:
            LOGGER.warning(
                "Valve entity %s unavailable for zone %s (entity %s)",
                runtime.config.valve_switch,
                zone_id,
                "not found" if current_valve_state is None else "unavailable",
            )
        elif runtime.state.valve_state == ValveState.UNKNOWN:
            LOGGER.warning(
                "Valve entity %s has unknown state for zone %s",
                runtime.config.valve_switch,
                zone_id,
            )

        # Track zone-level failure state
        self._update_zone_failure_state(
            runtime,
            now,
            temp_unavailable=temp_unavailable,
            recorder_failure=recorder_failure,
        )

    def _update_zone_failure_state(
        self,
        runtime: Any,  # ZoneRuntime
        now: datetime,
        *,
        temp_unavailable: bool,
        recorder_failure: bool,
    ) -> None:
        """Update zone failure tracking state."""
        state = runtime.state

        if temp_unavailable or recorder_failure:
            # Zone has a failure - increment counter and check for fail-safe
            state.consecutive_failures += 1

            # Check for zone-level fail-safe (1 hour timeout)
            if self._should_zone_fail_safe(state, now):
                if state.zone_status != ZoneStatus.FAIL_SAFE:
                    state.zone_status = ZoneStatus.FAIL_SAFE
                    LOGGER.error(
                        "Zone %s entering fail-safe mode after 1 hour of failures",
                        state.zone_id,
                    )
            elif state.zone_status == ZoneStatus.NORMAL:
                # Only transition to DEGRADED if we were previously NORMAL
                state.zone_status = ZoneStatus.DEGRADED
                LOGGER.warning(
                    "Zone %s entering degraded mode: temp_unavailable=%s, "
                    "recorder_failure=%s",
                    state.zone_id,
                    temp_unavailable,
                    recorder_failure,
                )
            # If zone is still INITIALIZING, keep it that way - don't report
            # problems before we've had a successful update
        else:
            # Zone succeeded - reset failure tracking
            if state.zone_status not in (ZoneStatus.NORMAL, ZoneStatus.INITIALIZING):
                LOGGER.info(
                    "Zone %s recovered from %s mode",
                    state.zone_id,
                    state.zone_status.value,
                )
            state.zone_status = ZoneStatus.NORMAL
            state.last_successful_update = now
            state.consecutive_failures = 0

    def _should_zone_fail_safe(self, state: Any, now: datetime) -> bool:
        """Check if a zone should enter fail-safe mode."""
        if state.last_successful_update is None:
            # First failure - start tracking
            state.last_successful_update = now
            return False

        elapsed = (now - state.last_successful_update).total_seconds()
        return elapsed > FAIL_SAFE_TIMEOUT

    def _update_controller_status_from_zones(self) -> None:
        """Update controller status based on zone statuses."""
        zone_statuses: list[ZoneStatus] = []
        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                zone_statuses.append(runtime.state.zone_status)

        if not zone_statuses:
            self._status = ControllerStatus.NORMAL
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
            self._status = ControllerStatus.INITIALIZING
        elif normal_count > 0:
            # At least one zone is normal - controller is operational
            if fail_safe_count > 0 or degraded_count > 0:
                self._status = ControllerStatus.DEGRADED
            else:
                self._status = ControllerStatus.NORMAL
        elif initializing_count > 0:
            # Some zones still initializing, but no zones are normal yet
            # Don't report fail-safe while zones are still initializing
            if fail_safe_count > 0 or degraded_count > 0:
                self._status = ControllerStatus.DEGRADED
            else:
                self._status = ControllerStatus.INITIALIZING
        elif fail_safe_count == len(zone_statuses):
            # ALL zones are in fail-safe (no normal, no initializing, no degraded)
            self._status = ControllerStatus.FAIL_SAFE
        else:
            # Mix of degraded and fail-safe, but no normal or initializing
            self._status = ControllerStatus.DEGRADED

    def _any_zone_in_fail_safe(self) -> bool:
        """Check if any zone is in fail-safe mode."""
        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if (
                runtime is not None
                and runtime.state.zone_status == ZoneStatus.FAIL_SAFE
            ):
                return True
        return False

    async def _execute_valve_actions(
        self,
        actions: dict[str, ZoneAction],
    ) -> None:
        """Execute valve actions by calling switch services."""
        for zone_id, action in actions.items():
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is None:
                continue

            valve_entity = runtime.config.valve_switch

            if action == ZoneAction.TURN_ON:
                await self._call_switch_service(valve_entity, turn_on=True)
            elif action == ZoneAction.TURN_OFF:
                await self._call_switch_service(valve_entity, turn_on=False)
            # STAY_ON and STAY_OFF don't require action

    async def _execute_valve_actions_with_isolation(
        self,
        actions: dict[str, ZoneAction],
    ) -> None:
        """Execute valve actions respecting zone-level fail-safe."""
        for zone_id, action in actions.items():
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is None:
                continue

            valve_entity = runtime.config.valve_switch

            # Zone in fail-safe: force valve closed, ignore normal action
            if runtime.state.zone_status == ZoneStatus.FAIL_SAFE:
                await self._call_switch_service(valve_entity, turn_on=False)
                runtime.state.valve_state = ValveState.OFF
                continue

            # Re-send commands when valve state is uncertain to force sync
            valve_uncertain = runtime.state.valve_state in (
                ValveState.UNKNOWN,
                ValveState.UNAVAILABLE,
            )

            # Normal action execution
            if action == ZoneAction.TURN_ON:
                await self._call_switch_service(valve_entity, turn_on=True)
            elif action == ZoneAction.TURN_OFF:
                await self._call_switch_service(valve_entity, turn_on=False)
            elif action == ZoneAction.STAY_ON and valve_uncertain:
                # Re-send turn_on to sync valve state
                await self._call_switch_service(valve_entity, turn_on=True)
            elif action == ZoneAction.STAY_OFF and valve_uncertain:
                # Re-send turn_off to sync valve state
                await self._call_switch_service(valve_entity, turn_on=False)

    async def _execute_heat_request(self, *, heat_request: bool) -> None:
        """Execute heat request by calling switch service if configured."""
        entity_id = self._controller.config.heat_request_entity
        if entity_id is None:
            return
        await self._call_switch_service(entity_id, turn_on=heat_request)

    async def _update_summer_mode(self, *, heat_request: bool) -> None:
        """
        Update boiler summer mode if configured.

        Safety: If ANY zone is in fail-safe, summer mode is forced to 'auto'
        to allow physical fallback valves to receive heated water.
        """
        entity_id = self._controller.config.summer_mode_entity
        if entity_id is None:
            return

        # Safety check: if any zone is in fail-safe, force summer mode to 'auto'
        if self._any_zone_in_fail_safe():
            summer_mode_value = SummerMode.AUTO
            LOGGER.debug(
                "Zone(s) in fail-safe, forcing summer mode to 'auto' for fallbacks"
            )
        else:
            summer_mode_value = self._controller.get_summer_mode_value(
                heat_request=heat_request
            )
            if summer_mode_value is None:
                return

        # Check current state
        current_state = self.hass.states.get(entity_id)
        if current_state is None:
            # Entity doesn't exist yet, can't update
            return
        if current_state.state == summer_mode_value:
            return  # Already in correct mode

        # Check if select service is available
        if not self.hass.services.has_service("select", "select_option"):
            LOGGER.debug(
                "Select service 'select_option' not available, skipping call to %s",
                entity_id,
            )
            return

        # Call select service to change mode
        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": summer_mode_value},
        )

    async def _call_switch_service(
        self,
        entity_id: str,
        *,
        turn_on: bool,
    ) -> None:
        """Call switch turn_on or turn_off service."""
        service = "turn_on" if turn_on else "turn_off"

        # Check if switch service is available
        if not self.hass.services.has_service("switch", service):
            LOGGER.debug(
                "Switch service '%s' not available, skipping call to %s",
                service,
                entity_id,
            )
            return

        await self.hass.services.async_call(
            "switch",
            service,
            {"entity_id": entity_id},
        )
        LOGGER.debug(
            "Switch service '%s' called for %s",
            service,
            entity_id,
        )

    def _build_state_dict(self) -> dict[str, Any]:
        """Build state dictionary for entities to consume."""
        # Count zones in each state
        zones_degraded = 0
        zones_fail_safe = 0
        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                if runtime.state.zone_status == ZoneStatus.DEGRADED:
                    zones_degraded += 1
                elif runtime.state.zone_status == ZoneStatus.FAIL_SAFE:
                    zones_fail_safe += 1

        result: dict[str, Any] = {
            "mode": self._controller.mode,
            "heat_request": self._controller.calculate_heat_request(),
            "observation_start": self._controller.state.observation_start,
            "controller_status": self._status.value,
            "zones_degraded": zones_degraded,
            "zones_fail_safe": zones_fail_safe,
            "zones": {},
        }

        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                state = runtime.state
                blocked = (
                    state.window_currently_open
                    or state.window_open_seconds
                    > self._controller.config.timing.window_block_time
                )
                heat_request = (
                    state.valve_state == ValveState.ON
                    and state.open_state_avg >= DEFAULT_VALVE_OPEN_THRESHOLD
                )

                result["zones"][zone_id] = {
                    "current": state.current,
                    "setpoint": state.setpoint,
                    "duty_cycle": state.duty_cycle,
                    "error": state.error,
                    "p_term": state.p_term,
                    "i_term": state.i_term,
                    "d_term": state.d_term,
                    "valve_state": state.valve_state.value,
                    "enabled": state.enabled,
                    "blocked": blocked,
                    "heat_request": heat_request,
                    "preset_mode": self._zone_presets.get(zone_id),
                    "zone_status": state.zone_status.value,
                }

        return result

    def set_zone_setpoint(self, zone_id: str, setpoint: float) -> None:
        """Set zone setpoint and trigger update."""
        if self._controller.set_zone_setpoint(zone_id, setpoint):
            self.async_set_updated_data(self._build_state_dict())
            self.hass.async_create_task(self.async_save_state())

    def set_zone_enabled(self, zone_id: str, *, enabled: bool) -> None:
        """Enable or disable a zone and trigger update."""
        if self._controller.set_zone_enabled(zone_id, enabled=enabled):
            self.async_set_updated_data(self._build_state_dict())
            self.hass.async_create_task(self.async_save_state())

    def set_mode(self, mode: str) -> None:
        """Set controller operation mode and trigger update."""
        self._controller.mode = mode
        self.async_set_updated_data(self._build_state_dict())
        self.hass.async_create_task(self.async_save_state())

    def set_zone_preset_mode(self, zone_id: str, preset_mode: str | None) -> None:
        """Set zone preset mode and trigger update."""
        self._zone_presets[zone_id] = preset_mode
        self.async_set_updated_data(self._build_state_dict())
        self.hass.async_create_task(self.async_save_state())
