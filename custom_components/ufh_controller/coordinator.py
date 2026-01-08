"""DataUpdateCoordinator for UFH Controller."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DEFAULT_VALVE_OPEN_THRESHOLD,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
    OperationMode,
)
from .core import (
    ControllerConfig,
    HeatingController,
    TimingParams,
    ZoneAction,
    ZoneConfig,
    get_duty_cycle_window,
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
    """Class to manage fetching UFH Controller data."""

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
            duty_cycle_window=timing_opts.get(
                "duty_cycle_window", DEFAULT_TIMING["duty_cycle_window"]
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
            window_block_threshold=timing_opts.get(
                "window_block_threshold", DEFAULT_TIMING["window_block_threshold"]
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

        # Update observation start
        timing = self._controller.config.timing
        self._controller.state.observation_start = get_observation_start(
            now, timing.observation_period
        )

        # Check DHW active state
        await self._update_dhw_state()

        # Update each zone
        for zone_id in self._controller.zone_ids:
            await self._update_zone(zone_id, now, dt)

        # Evaluate all zones and get actions
        actions = self._controller.evaluate_zones()

        # Execute valve actions
        await self._execute_valve_actions(actions)

        # Calculate and execute heat request
        heat_request = self._controller.calculate_heat_request()
        await self._execute_heat_request(heat_request=heat_request)

        # Update summer mode if configured
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

    async def _update_zone(
        self,
        zone_id: str,
        now: datetime,
        dt: float,
    ) -> None:
        """Update a single zone with current data and historical averages."""
        runtime = self._controller.get_zone_runtime(zone_id)
        if runtime is None:
            return

        # Read current temperature
        temp_state = self.hass.states.get(runtime.config.temp_sensor)
        current: float | None = None
        if temp_state is not None:
            try:
                current = float(temp_state.state)
            except (ValueError, TypeError):
                LOGGER.warning(
                    "Invalid temperature state for %s: %s",
                    runtime.config.temp_sensor,
                    temp_state.state,
                )

        # Update PID controller
        self._controller.update_zone_pid(zone_id, current, dt)

        # Query historical data from Recorder
        timing = self._controller.config.timing

        # Valve state since observation start (for used_duration)
        period_start = self._controller.state.observation_start
        period_state_avg = await get_state_average(
            self.hass,
            runtime.config.valve_switch,
            period_start,
            now,
            on_value="on",
        )

        # Valve state for open detection (recent window)
        valve_start, valve_end = get_valve_open_window(now, timing.valve_open_time)
        open_state_avg = await get_state_average(
            self.hass,
            runtime.config.valve_switch,
            valve_start,
            valve_end,
            on_value="on",
        )

        # Window sensors average
        duty_start, duty_end = get_duty_cycle_window(now, timing.duty_cycle_window)
        window_open_avg = await get_window_open_average(
            self.hass,
            runtime.config.window_sensors,
            duty_start,
            duty_end,
        )

        # Calculate elapsed time since observation start
        elapsed_time = (now - period_start).total_seconds()

        # Update zone with historical data
        self._controller.update_zone_historical(
            zone_id,
            period_state_avg=period_state_avg,
            open_state_avg=open_state_avg,
            window_open_avg=window_open_avg,
            elapsed_time=elapsed_time,
        )

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

    async def _execute_heat_request(self, *, heat_request: bool) -> None:
        """Execute heat request by calling switch service if configured."""
        entity_id = self._controller.config.heat_request_entity
        if entity_id is None:
            return
        await self._call_switch_service(entity_id, turn_on=heat_request)

    async def _update_summer_mode(self, *, heat_request: bool) -> None:
        """Update boiler summer mode if configured."""
        summer_mode_value = self._controller.get_summer_mode_value(
            heat_request=heat_request
        )
        if summer_mode_value is None:
            return

        entity_id = self._controller.config.summer_mode_entity
        if entity_id is None:
            return

        # Check current state
        current_state = self.hass.states.get(entity_id)
        if current_state is not None and current_state.state == summer_mode_value:
            return  # Already in correct mode

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

    def _build_state_dict(self) -> dict[str, Any]:
        """Build state dictionary for entities to consume."""
        result: dict[str, Any] = {
            "mode": self._controller.mode,
            "heat_request": self._controller.calculate_heat_request(),
            "observation_start": self._controller.state.observation_start,
            "zones": {},
        }

        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            if runtime is not None:
                state = runtime.state
                result["zones"][zone_id] = {
                    "current": state.current,
                    "setpoint": state.setpoint,
                    "duty_cycle": state.duty_cycle,
                    "error": state.error,
                    "p_term": state.p_term,
                    "i_term": state.i_term,
                    "d_term": state.d_term,
                    "valve_on": state.valve_on,
                    "enabled": state.enabled,
                    "window_blocked": state.window_open_avg
                    > self._controller.config.timing.window_block_threshold,
                    "is_requesting_heat": state.valve_on
                    and state.open_state_avg >= DEFAULT_VALVE_OPEN_THRESHOLD,
                    "preset_mode": self._zone_presets.get(zone_id),
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
