"""DataUpdateCoordinator for Underfloor Heating Controller."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from homeassistant.components.select import SERVICE_SELECT_OPTION
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON, Platform
from homeassistant.core import Event, callback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator
from sqlalchemy.exc import SQLAlchemyError

from .const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_SUPPLY_TARGET_TEMP,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
    DEFAULT_TEMP_EMA_TIME_CONSTANT,
    DEFAULT_TIMING,
    DOMAIN,
    INITIALIZING_UPDATE_INTERVAL,
    LOGGER,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
    ControllerStatus,
    OperationMode,
    SummerMode,
    TimingConfig,
    ValveState,
    ZoneStatus,
)
from .core.controller import ControllerConfig, HeatingController
from .core.heating_curve import HeatingCurveConfig
from .core.history import get_observation_start, get_valve_open_window
from .core.pid import PIDState
from .core.zone import (
    CircuitType,
    FailureStateResult,
    ZoneAction,
    ZoneConfig,
    ZoneStatusTransition,
)
from .recorder import get_state_average, was_any_window_open_recently

# Storage constants
STORAGE_VERSION = 2
STORAGE_KEY = "ufh_controller"


class UFHControllerStore(Store[dict[str, Any]]):
    """Store with V1→V2 migration support."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,  # noqa: ARG002
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate storage data to current version."""
        if old_major_version == 1:
            return self._migrate_v1_to_v2(old_data)
        return old_data

    @staticmethod
    def _migrate_v1_to_v2(old_data: dict[str, Any]) -> dict[str, Any]:
        """Migrate V1 storage format to V2 format."""
        # Build controller dict from V1 top-level keys
        controller = {
            "mode": old_data.get("controller_mode"),
            "flush_enabled": old_data.get("flush_enabled", False),
        }

        # Migrate zone data
        zones: dict[str, Any] = {}
        for zone_id, zone_state in old_data.get("zones", {}).items():
            migrated = {
                "setpoint": zone_state.get("setpoint"),
                "enabled": zone_state.get("enabled"),
                "preset_mode": zone_state.get("preset_mode"),
                "used_duration": zone_state.get("used_duration"),
                # PID key renames
                "pid_error": zone_state.get("error"),
                "pid_proportional": zone_state.get("p_term"),
                "pid_integral": zone_state.get("i_term"),
                "pid_derivative": zone_state.get("d_term"),
                "duty_cycle": zone_state.get("duty_cycle"),
                # Temperature: V1 "temperature" → V2 "current"
                "current": zone_state.get("temperature"),
                # display_temp: same key in both versions
                "display_temp": zone_state.get("display_temp"),
            }
            zones[zone_id] = {k: v for k, v in migrated.items() if v is not None}

        return {
            "controller": controller,
            "zones": zones,
            "last_update_success_time": old_data.get("last_update_success_time"),
            "last_force_update": old_data.get("last_force_update"),
        }


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import UFHControllerConfigEntry


class UFHControllerDataUpdateCoordinator(
    TimestampDataUpdateCoordinator[dict[str, Any]]
):
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
        self._status: ControllerStatus = ControllerStatus.INITIALIZING

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=INITIALIZING_UPDATE_INTERVAL),
        )
        self.config_entry = entry

        # Storage for crash resilience
        self._store = UFHControllerStore(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry.entry_id}",
        )
        self._state_restored: bool = False

        # Track previous DHW state for transition detection
        self._prev_dhw_active: bool = False

        # Track last force-update to ensure commands are sent at least once per cycle
        self._last_force_update: datetime | None = None

        # Track expected states for entities we control
        self._expected_states: dict[str, str | None] = {}

        # Track listener unsubscribe callback for re-setup on config reload
        self._listener_unsub: Callable[[], None] | None = None

    def _build_controller(self, entry: UFHControllerConfigEntry) -> HeatingController:
        """Build HeatingController from config entry."""
        data = entry.data

        # Get timing from controller subentry, fall back to options for migration
        timing_opts: dict[str, Any] = {}
        for subentry in entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
                timing_opts = subentry.data.get("timing", {})
                break

        timing = TimingConfig(
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
                    circuit_type=CircuitType(
                        zone_data.get("circuit_type", CircuitType.REGULAR)
                    ),
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

        # Build heating curve config from entry data
        heating_curve = HeatingCurveConfig(
            supply_target_temp=data.get(
                "supply_target_temp", DEFAULT_SUPPLY_TARGET_TEMP
            ),
            outdoor_temp_warm=data.get("outdoor_temp_warm", DEFAULT_OUTDOOR_TEMP_WARM),
            outdoor_temp_cold=data.get("outdoor_temp_cold", DEFAULT_OUTDOOR_TEMP_COLD),
            supply_temp_warm=data.get("supply_temp_warm", DEFAULT_SUPPLY_TEMP_WARM),
            supply_temp_cold=data.get("supply_temp_cold", DEFAULT_SUPPLY_TEMP_COLD),
        )

        config = ControllerConfig(
            controller_id=data["controller_id"],
            name=data["name"],
            heat_request_entity=data.get("heat_request_entity"),
            dhw_active_entity=data.get("dhw_active_entity"),
            summer_mode_entity=data.get("summer_mode_entity"),
            supply_temp_entity=data.get("supply_temp_entity"),
            outdoor_temp_entity=data.get("outdoor_temp_entity"),
            heating_curve=heating_curve,
            timing=timing,
            zones=zones,
        )

        return HeatingController(config)

    @property
    def controller(self) -> HeatingController:
        """Return the heating controller."""
        return self._controller

    async def async_load_stored_state(self) -> None:
        """Load state from storage (V2 format, migration handled by Store)."""
        if self._state_restored:
            return

        stored_data = await self._store.async_load()
        if stored_data is None:
            self._state_restored = True
            return

        # Data is already V2 format (Store handles migration)
        self._restore_timestamps(stored_data)

        controller_data = stored_data.get("controller", {})
        self._restore_controller_state(controller_data)

        zones_data = stored_data.get("zones", {})
        for zone_id, zone_state in zones_data.items():
            if zone_id in self._controller.zone_ids:
                self._restore_zone_state(zone_id, zone_state)

        self._state_restored = True

    def _restore_timestamps(self, stored_data: dict[str, Any]) -> None:
        """Restore timestamps from stored data."""
        if ts := stored_data.get("last_update_success_time"):
            with contextlib.suppress(ValueError, TypeError):
                self.last_update_success_time = datetime.fromisoformat(ts)

        if ts := stored_data.get("last_force_update"):
            with contextlib.suppress(ValueError, TypeError):
                self._last_force_update = datetime.fromisoformat(ts)

    async def async_config_entry_first_refresh(self) -> None:
        """Perform first refresh and set up state change listeners."""
        await super().async_config_entry_first_refresh()
        self._async_setup_listeners()

    def _async_setup_listeners(self) -> None:
        """Set up state change listeners for controller and zone entities."""
        # Unsubscribe from old listeners if they exist (for config reload)
        if self._listener_unsub is not None:
            self._listener_unsub()
            self._listener_unsub = None

        # Collect all configured entity IDs from config entry (skip None/empty)
        entity_ids: list[str] = []
        entry = self.config_entry

        # Controller-level entities
        if heat_request := entry.data.get("heat_request_entity"):
            entity_ids.append(heat_request)
        if summer_mode := entry.data.get("summer_mode_entity"):
            entity_ids.append(summer_mode)
        if dhw_active := entry.data.get("dhw_active_entity"):
            entity_ids.append(dhw_active)

        # Zone valve switches from subentries
        entity_ids.extend(
            subentry.data["valve_switch"]
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_ZONE
        )

        if not entity_ids:
            return

        # Subscribe to state changes
        self._listener_unsub = async_track_state_change_event(
            self.hass, entity_ids, self._on_external_entity_change
        )
        LOGGER.debug("Subscribed to state changes for entities: %s", entity_ids)

    @callback
    def shutdown(self) -> None:
        """
        Clean up resources on config entry unload.

        This method should be registered with async_on_unload() once during setup.
        It handles cleanup of listeners that may have been set up multiple times
        during in-place config reloads.
        """
        if self._listener_unsub is not None:
            self._listener_unsub()
            self._listener_unsub = None
            LOGGER.debug("Unsubscribed state change listeners on shutdown")

    @callback
    def _on_external_entity_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle state changes for monitored entities."""
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]

        if new_state is None:
            # entity removed; ignore the event
            return

        # Check if this state change matches what we expected (self-initiated change)
        expected = self._expected_states.get(entity_id)
        if expected is not None and new_state.state == expected:
            # clear expectation; ignore the event
            self._expected_states[entity_id] = None
            return

        # External change - request refresh
        old_state = event.data.get("old_state")
        old_state_str = old_state.state if old_state else None
        LOGGER.debug(
            "External state change detected for %s: %s -> %s, requesting refresh",
            entity_id,
            old_state_str,
            new_state.state,
        )
        self.hass.async_create_task(self.async_request_refresh())

    def _restore_zone_state(self, zone_id: str, zone_state: dict[str, Any]) -> None:
        """Restore state for a single zone from V2 storage format."""
        runtime = self._controller.get_zone_runtime(zone_id)

        # Restore full PID state if available (only if not yet calculated)
        if runtime.pid.state is None and "duty_cycle" in zone_state:
            pid_state = PIDState(
                error=zone_state.get("pid_error", 0.0),
                p_term=zone_state.get("pid_proportional", 0.0),
                i_term=zone_state.get("pid_integral", 0.0),
                d_term=zone_state.get("pid_derivative", 0.0),
                duty_cycle=zone_state.get("duty_cycle", 0.0),
            )
            runtime.pid.set_state(pid_state)

        if (
            "setpoint" in zone_state
            and zone_state["setpoint"] != runtime.state.setpoint
        ):
            self._controller.set_zone_setpoint(zone_id, zone_state["setpoint"])

        if "enabled" in zone_state and zone_state["enabled"] != runtime.state.enabled:
            self._controller.set_zone_enabled(zone_id, enabled=zone_state["enabled"])

        if "preset_mode" in zone_state:
            runtime.state.preset_mode = zone_state["preset_mode"]

        # Restore EMA-smoothed temperature for PID continuity
        if "current" in zone_state:
            runtime.state.current = zone_state["current"]

        # Restore display temperature for immediate climate entity availability
        if "display_temp" in zone_state:
            runtime.state.display_temp = zone_state["display_temp"]

        if "used_duration" in zone_state:
            runtime.state.used_duration = zone_state["used_duration"]

    def _build_storage_state(self) -> dict[str, Any]:
        """Build state dictionary for persistent storage."""
        data: dict[str, Any] = {
            "controller": self.data["controller"],
            "zones": self.data["zones"],
        }

        # Include last update timestamp from base class
        if self.last_update_success_time is not None:
            data["last_update_success_time"] = self.last_update_success_time.isoformat()

        # Include last force update timestamp for observation period tracking
        if self._last_force_update is not None:
            data["last_force_update"] = self._last_force_update.isoformat()

        return data

    async def async_save_state(self) -> None:
        """Save current state to storage."""
        data = self._build_storage_state()
        await self._store.async_save(data)

    def _async_refresh_finished(self) -> None:
        """
        Handle when a refresh has finished - persist state after successful updates.

        This hook is called after a coordinator refresh completes but before
        listeners are notified. The TimestampDataUpdateCoordinator base class
        automatically updates last_update_success_time on successful refreshes.

        We use this hook to trigger state persistence (including the timestamp)
        for crash resilience.
        """
        # Call parent hook first (updates last_update_success_time)
        super()._async_refresh_finished()

        # Only persist state after successful updates
        if self.last_update_success:
            self.hass.async_create_task(self.async_save_state())

    @property
    def status(self) -> ControllerStatus:
        """Return the current controller operational status."""
        return self._status

    async def _execute_fail_safe_actions(self) -> None:
        """Execute fail-safe mode actions - close all valves and disable heating."""
        # Close all valves
        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            await self._call_switch_service(runtime.config.valve_switch, turn_on=False)
            # Update zone state to reflect valve is off
            runtime.state.valve_state = ValveState.OFF

        # Turn off heat request
        await self._execute_heat_request(heat_request=False)

        # Set summer mode to 'auto' to pass control back to the boiler
        summer_entity = self._controller.config.summer_mode_entity
        if summer_entity:
            # Track expected state for external change detection
            self._expected_states[summer_entity] = SummerMode.AUTO

            await self.hass.services.async_call(
                Platform.SELECT,
                SERVICE_SELECT_OPTION,
                {"entity_id": summer_entity, "option": SummerMode.AUTO},
            )
            LOGGER.debug(
                "Select service '%s' called for %s with option '%s'",
                SERVICE_SELECT_OPTION,
                summer_entity,
                SummerMode.AUTO,
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via controller logic."""
        # Load stored state on first run (fallback restoration)
        if not self._state_restored:
            await self.async_load_stored_state()

        now = datetime.now(UTC)
        timing = self._controller.config.timing

        if self.last_update_success_time is not None:
            # Calculate time since last update using base class timestamp
            # Cap dt to prevent integral windup after long downtime (e.g., restored
            # timestamp from a day ago). Max dt is 2x normal update interval.
            max_dt = 2 * timing.controller_loop_interval
            dt = min((now - self.last_update_success_time).total_seconds(), max_dt)
        else:
            # Use default update interval if no previous update
            dt = timing.controller_loop_interval

        # Skip if no zones configured
        if not self._controller.zone_ids:
            return self._build_state_dict()

        # Handle observation period transition
        force_update = self._handle_observation_period_transition(now)

        # Check DHW active state
        await self._update_dhw_state()

        # Update outdoor temperature and calculate supply target for heating curve
        self._set_outdoor_temp()

        # Update each zone (each zone tracks its own failure state)
        for zone_id in self._controller.zone_ids:
            await self._update_zone(zone_id, now, dt)

        previous_status = self._status

        # Update controller status from zone statuses
        self._update_controller_status_from_zones()

        # Detect initialization finished
        if (
            previous_status == ControllerStatus.INITIALIZING
            and previous_status != self._status
        ):
            self.update_interval = timedelta(
                seconds=self._controller.config.timing.controller_loop_interval
            )

        # If ALL zones are in fail-safe, execute controller-level fail-safe
        if self._status == ControllerStatus.FAIL_SAFE:
            await self._execute_fail_safe_actions()
            return self._build_state_dict()

        # Skip zone evaluation while initializing
        if self._status == ControllerStatus.INITIALIZING:
            return self._build_state_dict()

        # Evaluate all zones and get all actions
        actions = self._controller.evaluate(now=now)

        # Update flush_request state for binary_sensor exposure
        self._controller.state.flush_request = actions.flush_request

        # Update per-zone heat requests from controller output
        self._controller.state.heat_requests = actions.heat_requests

        # Execute valve actions with zone-level isolation
        await self._execute_valve_actions_with_isolation(
            actions.valve_actions, force_update=force_update
        )

        # Execute heat request and summer mode
        if actions.heat_requests:
            # Compute and set heat request from per-zone requests
            heat_request = any(actions.heat_requests.values())
            await self._execute_heat_request(
                heat_request=heat_request, force_update=force_update
            )

            # Derive and update summer mode from heat_request
            summer_mode = SummerMode.WINTER if heat_request else SummerMode.SUMMER
            await self._set_summer_mode(summer_mode, force_update=force_update)

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

        # Clear flush_until when DHW starts
        if current_dhw_active and not self._prev_dhw_active:
            self._controller.state.flush_until = None

        # Update current state
        self._prev_dhw_active = current_dhw_active
        self._controller.state.dhw_active = current_dhw_active

    def _handle_observation_period_transition(self, now: datetime) -> bool:
        """
        Handle observation period transition and return whether force update is needed.

        This method:
        1. Updates observation_start and period_elapsed
        2. Detects if we've transitioned to a new observation period
        3. Resets used_duration for all zones on period transition
        4. Updates _last_force_update timestamp

        Returns True if force update is needed (new period started).
        """
        timing = self._controller.config.timing

        # Update observation start and elapsed time
        self._controller.state.observation_start = get_observation_start(
            now, timing.observation_period
        )
        self._controller.state.period_elapsed = (
            now - self._controller.state.observation_start
        ).total_seconds()

        # Check if we've transitioned to a new observation period
        new_period = (
            self._last_force_update is None
            or self._last_force_update < self._controller.state.observation_start
        )

        if new_period:
            # Reset used_duration for all zones at period boundary
            for runtime in self._controller.zone_runtimes:
                runtime.reset_used_duration()

            # Mark this period as handled
            self._last_force_update = now

        return new_period

    def _get_supply_temp(self) -> float | None:
        """Get current supply temperature if available."""
        supply_entity = self._controller.config.supply_temp_entity
        if supply_entity is None:
            return None
        supply_state = self.hass.states.get(supply_entity)
        if supply_state is None:
            return None
        try:
            return float(supply_state.state)
        except (ValueError, TypeError):
            return None

    def _get_outdoor_temp(self) -> float | None:
        """Get current outdoor temperature if available."""
        outdoor_entity = self._controller.config.outdoor_temp_entity
        if outdoor_entity is None:
            return None
        outdoor_state = self.hass.states.get(outdoor_entity)
        if outdoor_state is None:
            return None
        try:
            return float(outdoor_state.state)
        except (ValueError, TypeError):
            return None

    def _set_outdoor_temp(self) -> None:
        """
        Update outdoor temperature on the controller.

        Reads the outdoor sensor and calls the controller's update method,
        which calculates the supply target from the heating curve.
        This must be called once per update cycle, before zone evaluation.
        """
        outdoor_temp = self._get_outdoor_temp()
        curve_config = self._controller.config.heating_curve

        # Log warning for invalid curve configuration
        if outdoor_temp is not None and not curve_config.is_valid():
            LOGGER.warning(
                "Invalid heating curve: outdoor_temp_warm (%.1f) must be > "
                "outdoor_temp_cold (%.1f), using fallback supply_target_temp",
                curve_config.outdoor_temp_warm,
                curve_config.outdoor_temp_cold,
            )

        self._controller.set_outdoor_temp(outdoor_temp)

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
            LOGGER.warning(
                "Temperature entity %s not found for zone %s",
                runtime.config.temp_sensor,
                zone_id,
            )

        # Update PID controller
        runtime.update_pid(dt, self._controller.mode)

        # Update requested_duration from current duty cycle
        timing = self._controller.config.timing
        runtime.update_requested_duration(timing.observation_period)

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
            open_state_avg=open_state_avg,
            window_recently_open=window_recently_open,
        )

        # Update supply coefficient from supply temperature
        # Supply target is calculated once per cycle and stored in controller state
        supply_temp = self._get_supply_temp()
        supply_target = self._controller.state.supply_target_temp
        if supply_target is not None:
            runtime.update_supply_coefficient(
                supply_temp=supply_temp,
                supply_target_temp=supply_target,
            )

        # Update used_duration based on flow and heat performance
        runtime.update_used_duration(dt)

        # Sync valve state from actual HA entity
        # This ensures we detect when external factors change the valve state
        # (e.g., user toggle, automation, device reset)
        current_valve_state = self.hass.states.get(runtime.config.valve_switch)
        runtime.state.valve_state = ValveState.from_ha_state(current_valve_state)

        # Determine if valve entity is unavailable or unknown
        valve_unavailable = runtime.state.valve_state in (
            ValveState.UNAVAILABLE,
            ValveState.UNKNOWN,
        )

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
        result = runtime.update_failure_state(
            now,
            temp_unavailable=temp_unavailable,
            valve_unavailable=valve_unavailable,
        )
        self._log_zone_status_transition(
            zone_id,
            result,
            temp_unavailable=temp_unavailable,
            valve_unavailable=valve_unavailable,
        )

    def _log_zone_status_transition(
        self,
        zone_id: str,
        result: FailureStateResult,
        *,
        temp_unavailable: bool,
        valve_unavailable: bool,
    ) -> None:
        """Log zone status transitions (integration layer's responsibility)."""
        if result.transition == ZoneStatusTransition.ENTERED_FAIL_SAFE:
            LOGGER.error(
                "Zone %s entering fail-safe mode after %d seconds of failures",
                zone_id,
                result.timeout_used,
            )
        elif result.transition == ZoneStatusTransition.ENTERED_DEGRADED:
            LOGGER.warning(
                "Zone %s entering degraded mode: temp_unavailable=%s, "
                "valve_unavailable=%s",
                zone_id,
                temp_unavailable,
                valve_unavailable,
            )
        elif result.transition == ZoneStatusTransition.RECOVERED:
            LOGGER.info("Zone %s recovered to normal operation", zone_id)

    def _update_controller_status_from_zones(self) -> None:
        """Update controller status based on zone statuses."""
        zone_statuses = [
            self._controller.get_zone_runtime(zone_id).state.zone_status
            for zone_id in self._controller.zone_ids
        ]

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
        return any(
            self._controller.get_zone_runtime(zone_id).state.zone_status
            == ZoneStatus.FAIL_SAFE
            for zone_id in self._controller.zone_ids
        )

    async def _execute_valve_actions(
        self,
        actions: dict[str, ZoneAction],
    ) -> None:
        """Execute valve actions by calling switch services."""
        for zone_id, action in actions.items():
            runtime = self._controller.get_zone_runtime(zone_id)
            valve_entity = runtime.config.valve_switch

            if action == ZoneAction.TURN_ON:
                await self._call_switch_service(valve_entity, turn_on=True)
            elif action == ZoneAction.TURN_OFF:
                await self._call_switch_service(valve_entity, turn_on=False)
            # STAY_ON and STAY_OFF don't require action

    async def _execute_valve_actions_with_isolation(
        self,
        actions: dict[str, ZoneAction],
        *,
        force_update: bool = False,
    ) -> None:
        """Execute valve actions respecting zone-level fail-safe."""
        for zone_id, action in actions.items():
            runtime = self._controller.get_zone_runtime(zone_id)
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
                if force_update or runtime.state.valve_state != ValveState.ON:
                    await self._call_switch_service(valve_entity, turn_on=True)
                runtime.state.valve_state = ValveState.ON
            elif action == ZoneAction.STAY_OFF:
                if force_update or runtime.state.valve_state != ValveState.OFF:
                    await self._call_switch_service(valve_entity, turn_on=False)
                runtime.state.valve_state = ValveState.OFF

    async def _execute_heat_request(
        self, *, heat_request: bool, force_update: bool = False
    ) -> None:
        """Execute heat request by calling switch service if configured."""
        entity_id = self._controller.config.heat_request_entity
        if entity_id is None:
            return

        if not force_update:
            current_state = self.hass.states.get(entity_id)
            if current_state is not None:
                current_on = current_state.state == "on"
                if current_on == heat_request:
                    return  # Already in correct state

        await self._call_switch_service(entity_id, turn_on=heat_request)

    async def _set_summer_mode(
        self, summer_mode: SummerMode, *, force_update: bool = False
    ) -> None:
        """
        Set boiler summer mode to specified value.

        Safety: If ANY zone is in fail-safe, summer mode is forced to 'auto'
        to allow physical fallback valves to receive heated water.
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

        current_state = self.hass.states.get(entity_id)
        if current_state is None:
            return
        if not force_update and current_state.state == summer_mode:
            return  # Already in correct mode

        # Check if select service is available
        if not self.hass.services.has_service(Platform.SELECT, SERVICE_SELECT_OPTION):
            LOGGER.debug(
                "Select service '%s' not available, skipping call to %s",
                SERVICE_SELECT_OPTION,
                entity_id,
            )
            return

        # Track expected state for external change detection
        self._expected_states[entity_id] = summer_mode

        # Call select service to change mode
        await self.hass.services.async_call(
            Platform.SELECT,
            SERVICE_SELECT_OPTION,
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
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF

        # Check if switch service is available
        if not self.hass.services.has_service(Platform.SWITCH, service):
            LOGGER.debug(
                "Switch service '%s' not available, skipping call to %s",
                service,
                entity_id,
            )
            return

        # Track expected state for external change detection
        self._expected_states[entity_id] = "on" if turn_on else "off"

        await self.hass.services.async_call(
            Platform.SWITCH,
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
        zone_statuses = [
            self._controller.get_zone_runtime(zone_id).state.zone_status
            for zone_id in self._controller.zone_ids
        ]
        zones_degraded = sum(1 for s in zone_statuses if s == ZoneStatus.DEGRADED)
        zones_fail_safe = sum(1 for s in zone_statuses if s == ZoneStatus.FAIL_SAFE)

        # Count zones requesting heat from controller state
        requesting_zones = sum(self._controller.state.heat_requests.values())

        result: dict[str, Any] = {
            "controller": {
                "mode": self._controller.mode,
                "requesting_zones": requesting_zones,
                "observation_start": self._controller.state.observation_start,
                "period_elapsed": self._controller.state.period_elapsed,
                "status": self._status.value,
                "zones_degraded": zones_degraded,
                "zones_fail_safe": zones_fail_safe,
                "flush_enabled": self._controller.state.flush_enabled,
                "dhw_active": self._controller.state.dhw_active,
                "flush_until": self._controller.state.flush_until,
                "flush_request": self._controller.state.flush_request,
                "outdoor_temp": self._controller.state.outdoor_temp,
                "supply_target_temp": self._controller.state.supply_target_temp,
            },
            "zones": {},
        }

        for zone_id in self._controller.zone_ids:
            runtime = self._controller.get_zone_runtime(zone_id)
            state = runtime.state
            pid_state = runtime.pid.state
            # Blocked now means PID is paused due to recent window activity
            blocked = state.window_recently_open

            result["zones"][zone_id] = {
                "current": state.current,
                "display_temp": state.display_temp,
                "setpoint": state.setpoint,
                "duty_cycle": pid_state.duty_cycle if pid_state else None,
                "pid_error": pid_state.error if pid_state else None,
                "pid_proportional": pid_state.p_term if pid_state else None,
                "pid_integral": pid_state.i_term if pid_state else None,
                "pid_derivative": pid_state.d_term if pid_state else None,
                "valve_state": state.valve_state.value,
                "enabled": state.enabled,
                "blocked": blocked,
                "heat_request": self._controller.state.heat_requests.get(
                    zone_id, False
                ),
                "flow": state.flow,
                "preset_mode": state.preset_mode,
                "zone_status": state.zone_status.value,
                "supply_coefficient": state.supply_coefficient,
                "used_duration": state.used_duration,
            }

        return result

    async def set_zone_setpoint(self, zone_id: str, setpoint: float) -> None:
        """Set zone setpoint and trigger refresh."""
        if self._controller.set_zone_setpoint(zone_id, setpoint):
            await self.async_request_refresh()

    async def set_zone_enabled(self, zone_id: str, *, enabled: bool) -> None:
        """Enable or disable a zone and trigger refresh."""
        if self._controller.set_zone_enabled(zone_id, enabled=enabled):
            await self.async_request_refresh()

    async def set_mode(self, mode: str) -> None:
        """Set controller operation mode and trigger refresh."""
        self._controller.mode = mode
        await self.async_request_refresh()

    async def set_zone_preset_mode(self, zone_id: str, preset_mode: str | None) -> None:
        """Set zone preset mode and trigger refresh."""
        runtime = self._controller.get_zone_runtime(zone_id)
        runtime.state.preset_mode = preset_mode
        await self.async_request_refresh()

    async def set_flush_enabled(self, *, enabled: bool) -> None:
        """Enable or disable flush and trigger refresh."""
        self._controller.state.flush_enabled = enabled
        await self.async_request_refresh()

    def _restore_controller_state(self, controller_data: dict[str, Any]) -> None:
        """Restore controller-level state from V2 storage format."""
        if "mode" in controller_data:
            stored_mode = controller_data["mode"]
            if stored_mode in [mode.value for mode in OperationMode]:
                self._controller.mode = stored_mode

        if "flush_enabled" in controller_data:
            self._controller.state.flush_enabled = controller_data["flush_enabled"]

    async def async_reload_config(self) -> None:
        """
        Reload controller configuration in-place without entity recreation.

        This method rebuilds the controller from updated config entry data while
        preserving runtime state (PID state, setpoints, enabled flags). This allows
        parameter tuning (PID, timing, setpoints) without entity state resets.

        Uses the same state management infrastructure as async_save_state() and
        async_load_stored_state() to ensure consistency and avoid duplication.
        """
        LOGGER.debug("Reloading controller config in-place")

        # Refresh to update self.data with latest runtime state before capturing
        await self.async_refresh()

        # Capture current state using existing state management
        old_zone_ids = set(self._controller.zone_ids)
        saved_state = self._build_storage_state()

        # Preserve flush_until separately (not persisted to storage)
        saved_flush_until = self._controller.state.flush_until

        # Rebuild controller with updated config
        self._controller = self._build_controller(self.config_entry)

        # Restore controller-level state using existing method (V2 format)
        controller_data = saved_state.get("controller", {})
        self._restore_controller_state(controller_data)

        # Restore flush_until (runtime-only state)
        self._controller.state.flush_until = saved_flush_until

        # Restore zone state for zones that still exist using existing method
        new_zone_ids = set(self._controller.zone_ids)
        zones_data = saved_state.get("zones", {})
        for zone_id in new_zone_ids & old_zone_ids:  # Intersection
            if zone_id in zones_data:
                self._restore_zone_state(zone_id, zones_data[zone_id])

        LOGGER.debug(
            "Config reloaded in-place: zones_before=%d, zones_after=%d",
            len(old_zone_ids),
            len(new_zone_ids),
        )

        # Re-setup listeners in case controller entities changed
        self._async_setup_listeners()

        # Trigger refresh to update entities with new config
        await self.async_request_refresh()
