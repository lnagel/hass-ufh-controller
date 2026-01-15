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
    DEFAULT_TEMP_EMA_TIME_CONSTANT,
    DEFAULT_TIMING,
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
    PIDState,
    TimingParams,
    ZoneAction,
    ZoneConfig,
    ZoneStatusTransition,
    get_observation_start,
    get_valve_open_window,
    should_request_heat,
)
from .core.zone import CircuitType
from .recorder import get_state_average, was_any_window_open_recently

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

        # Track previous DHW state for transition detection
        self._prev_dhw_active: bool = False

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
            flush_duration=timing_opts.get(
                "flush_duration", DEFAULT_TIMING["flush_duration"]
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
                    temp_ema_time_constant=zone_data.get(
                        "temp_ema_time_constant", DEFAULT_TEMP_EMA_TIME_CONSTANT
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

        # Restore flush_enabled state
        if "flush_enabled" in stored_data:
            self._controller.state.flush_enabled = stored_data["flush_enabled"]

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

        # Restore full PID state if available (only if not yet calculated)
        if runtime.pid.state is None and "duty_cycle" in zone_state:
            pid_state = PIDState(
                error=zone_state.get("error", 0.0),
                p_term=zone_state.get("p_term", 0.0),
                i_term=zone_state.get("i_term", 0.0),
                d_term=zone_state.get("d_term", 0.0),
                duty_cycle=zone_state.get("duty_cycle", 0.0),
            )
            runtime.pid.set_state(pid_state)

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

        # Restore temperature (EMA value) for smooth continuity across restarts
        if "temperature" in zone_state:
            runtime.state.current = zone_state["temperature"]

    async def async_save_state(self) -> None:
        """Save current state to storage."""
        zones_data: dict[str, dict[str, Any]] = {}

        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                zone_data: dict[str, Any] = {
                    "setpoint": runtime.state.setpoint,
                    "enabled": runtime.state.enabled,
                }
                # Save full PID state if available
                if runtime.pid.state is not None:
                    zone_data["error"] = runtime.pid.state.error
                    zone_data["p_term"] = runtime.pid.state.p_term
                    zone_data["i_term"] = runtime.pid.state.i_term
                    zone_data["d_term"] = runtime.pid.state.d_term
                    zone_data["duty_cycle"] = runtime.pid.state.duty_cycle
                # Include preset_mode if set
                preset_mode = self._zone_presets.get(zone_id)
                if preset_mode is not None:
                    zone_data["preset_mode"] = preset_mode
                # Save temperature (EMA value) for smooth continuity across restarts
                if runtime.state.current is not None:
                    zone_data["temperature"] = runtime.state.current
                zones_data[zone_id] = zone_data

        data = {
            "version": STORAGE_VERSION,
            "saved_at": datetime.now(UTC).isoformat(),
            "controller_mode": self._controller.mode,
            "flush_enabled": self._controller.state.flush_enabled,
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
            LOGGER.debug(
                "Select service 'select_option' called for %s with option '%s'",
                summer_entity,
                SummerMode.AUTO,
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

        # Evaluate all zones and get all actions
        actions = self._controller.evaluate(now=now)

        # Update flush_request state for binary_sensor exposure
        self._controller.state.flush_request = actions.flush_request

        # Execute valve actions with zone-level isolation
        await self._execute_valve_actions_with_isolation(actions.valve_actions)

        # Execute heat request and summer mode
        if actions.heat_request is not None:
            self._controller.state.heat_request = actions.heat_request
            await self._execute_heat_request(heat_request=actions.heat_request)

            # Derive and update summer mode from heat_request
            summer_mode = (
                SummerMode.WINTER if actions.heat_request else SummerMode.SUMMER
            )
            await self._set_summer_mode(summer_mode)

        # Save state after every update for crash resilience
        await self.async_save_state()

        return self._build_state_dict()

    async def _update_dhw_state(self) -> None:
        """Update DHW active state from entity and manage post-DHW flush timer."""
        dhw_entity = self._controller.config.dhw_active_entity
        if dhw_entity is None:
            return

        state = self.hass.states.get(dhw_entity)
        current_dhw_active = state is not None and state.state == "on"

        # Detect DHW OFF transition (was on, now off)
        if self._prev_dhw_active and not current_dhw_active:
            # DHW just turned off - start post-flush timer if enabled
            flush_duration = self._controller.config.timing.flush_duration
            if flush_duration > 0 and self._controller.state.flush_enabled:
                self._controller.state.flush_until = datetime.now(UTC) + timedelta(
                    seconds=flush_duration
                )
                LOGGER.debug(
                    "DHW ended, flush will continue until %s",
                    self._controller.state.flush_until,
                )

        # Clear flush_until when DHW starts (will use dhw_active instead)
        if current_dhw_active and not self._prev_dhw_active:
            self._controller.state.flush_until = None

        # Update current state
        self._prev_dhw_active = current_dhw_active
        self._controller.state.dhw_active = current_dhw_active

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

        # Read current temperature and update zone
        temp_state = self.hass.states.get(runtime.config.temp_sensor)
        temp_unavailable = False
        if temp_state is not None:
            try:
                raw_temp = float(temp_state.state)
                # Update temperature with EMA smoothing
                runtime.update_temperature(raw_temp, dt)
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
        runtime.update_pid(dt, self._controller.mode)

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

        # NON-CRITICAL: Check if any window was open recently
        # This query checks the last window_block_time seconds to determine
        # if PID should be paused. Fallback: Check current window state.
        try:
            window_recently_open = await was_any_window_open_recently(
                self.hass,
                runtime.config.window_sensors,
                now,
                timing.window_block_time,
            )
        except SQLAlchemyError:
            # Fallback to current window state if Recorder unavailable
            window_recently_open = self._is_any_window_open(
                runtime.config.window_sensors
            )
            LOGGER.warning(
                "Recorder query failed for recent window state, "
                "using current state for zone %s: %s",
                zone_id,
                window_recently_open,
                exc_info=True,
            )

        # Update zone with historical data
        runtime.update_historical(
            period_state_avg=period_state_avg,
            open_state_avg=open_state_avg,
            window_recently_open=window_recently_open,
            elapsed_time=self._controller.state.period_elapsed,
            observation_period=timing.observation_period,
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
        transition = runtime.update_failure_state(
            now,
            temp_unavailable=temp_unavailable,
            recorder_failure=recorder_failure,
            fail_safe_timeout=FAIL_SAFE_TIMEOUT,
        )
        self._log_zone_status_transition(
            zone_id,
            transition,
            temp_unavailable=temp_unavailable,
            recorder_failure=recorder_failure,
        )

    def _log_zone_status_transition(
        self,
        zone_id: str,
        transition: ZoneStatusTransition,
        *,
        temp_unavailable: bool,
        recorder_failure: bool,
    ) -> None:
        """Log zone status transitions (integration layer's responsibility)."""
        if transition == ZoneStatusTransition.ENTERED_FAIL_SAFE:
            LOGGER.error(
                "Zone %s entering fail-safe mode after %d seconds of failures",
                zone_id,
                FAIL_SAFE_TIMEOUT,
            )
        elif transition == ZoneStatusTransition.ENTERED_DEGRADED:
            LOGGER.warning(
                "Zone %s entering degraded mode: temp_unavailable=%s, "
                "recorder_failure=%s",
                zone_id,
                temp_unavailable,
                recorder_failure,
            )
        elif transition == ZoneStatusTransition.RECOVERED:
            LOGGER.info("Zone %s recovered to normal operation", zone_id)

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

            # Normal action execution
            if action == ZoneAction.TURN_ON:
                await self._call_switch_service(valve_entity, turn_on=True)
                runtime.state.valve_state = ValveState.ON
            elif action == ZoneAction.TURN_OFF:
                await self._call_switch_service(valve_entity, turn_on=False)
                runtime.state.valve_state = ValveState.OFF
            elif action == ZoneAction.STAY_ON:
                if runtime.state.valve_state != ValveState.ON:
                    await self._call_switch_service(valve_entity, turn_on=True)
                runtime.state.valve_state = ValveState.ON
            elif action == ZoneAction.STAY_OFF:
                if runtime.state.valve_state != ValveState.OFF:
                    await self._call_switch_service(valve_entity, turn_on=False)
                runtime.state.valve_state = ValveState.OFF

    async def _execute_heat_request(self, *, heat_request: bool) -> None:
        """Execute heat request by calling switch service if configured."""
        entity_id = self._controller.config.heat_request_entity
        if entity_id is None:
            return

        # Check current entity state - only update if different
        current_state = self.hass.states.get(entity_id)
        if current_state is not None:
            current_on = current_state.state == "on"
            if current_on == heat_request:
                return  # Already in correct state

        await self._call_switch_service(entity_id, turn_on=heat_request)

    async def _set_summer_mode(self, summer_mode: SummerMode) -> None:
        """
        Set boiler summer mode to specified value.

        Safety: If ANY zone is in fail-safe, summer mode is forced to 'auto'
        to allow physical fallback valves to receive heated water.

        Args:
            summer_mode: The summer mode value to set.

        """
        entity_id = self._controller.config.summer_mode_entity
        if entity_id is None:
            return

        # Safety check: if any zone is in fail-safe, force summer mode to 'auto'
        if self._any_zone_in_fail_safe():
            summer_mode = SummerMode.AUTO
            LOGGER.debug(
                "Zone(s) in fail-safe, forcing summer mode to 'auto' for fallbacks"
            )

        # Check current state
        current_state = self.hass.states.get(entity_id)
        if current_state is None:
            return
        if current_state.state == summer_mode:
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
            {"entity_id": entity_id, "option": summer_mode},
        )
        LOGGER.debug(
            "Set summer mode for %s to '%s'",
            entity_id,
            summer_mode,
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
            "heat_request": self._controller.state.heat_request,
            "observation_start": self._controller.state.observation_start,
            "controller_status": self._status.value,
            "zones_degraded": zones_degraded,
            "zones_fail_safe": zones_fail_safe,
            "flush_request": self._controller.state.flush_request,
            "zones": {},
        }

        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                state = runtime.state
                pid_state = runtime.pid.state
                # Blocked now means PID is paused due to recent window activity
                blocked = state.window_recently_open

                result["zones"][zone_id] = {
                    "current": state.display_temp,
                    "setpoint": state.setpoint,
                    "duty_cycle": pid_state.duty_cycle if pid_state else None,
                    "error": pid_state.error if pid_state else None,
                    "p_term": pid_state.p_term if pid_state else None,
                    "i_term": pid_state.i_term if pid_state else None,
                    "d_term": pid_state.d_term if pid_state else None,
                    "valve_state": state.valve_state.value,
                    "enabled": state.enabled,
                    "blocked": blocked,
                    "heat_request": should_request_heat(
                        state, self._controller.config.timing
                    ),
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
