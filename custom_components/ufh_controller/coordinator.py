"""DataUpdateCoordinator for UFH Controller."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONTROLLER_LOOP_INTERVAL, DOMAIN, LOGGER
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
from .core.zone import _VALVE_OPEN_THRESHOLD, CircuitType

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
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=CONTROLLER_LOOP_INTERVAL),
        )
        self.config_entry = entry
        self._last_update: datetime | None = None

        # Build controller from config entry
        self._controller = self._build_controller(entry)

    def _build_controller(self, entry: UFHControllerConfigEntry) -> HeatingController:
        """Build HeatingController from config entry."""
        data = entry.data
        options = entry.options

        timing_opts = options.get("timing", {})
        timing = TimingParams(
            observation_period=timing_opts.get("observation_period", 7200),
            duty_cycle_window=timing_opts.get("duty_cycle_window", 3600),
            min_run_time=timing_opts.get("min_run_time", 540),
            valve_open_time=timing_opts.get("valve_open_time", 210),
            closing_warning_duration=timing_opts.get("closing_warning_duration", 240),
            window_block_threshold=timing_opts.get("window_block_threshold", 0.05),
        )

        zones: list[ZoneConfig] = []
        for zone_data in options.get("zones", []):
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
                    setpoint_min=setpoint_opts.get("min", 16.0),
                    setpoint_max=setpoint_opts.get("max", 28.0),
                    setpoint_default=setpoint_opts.get("default", 21.0),
                    kp=pid_opts.get("kp", 50.0),
                    ki=pid_opts.get("ki", 0.05),
                    kd=pid_opts.get("kd", 0.0),
                    integral_min=pid_opts.get("integral_min", 0.0),
                    integral_max=pid_opts.get("integral_max", 100.0),
                )
            )

        config = ControllerConfig(
            controller_id=data["controller_id"],
            name=data["name"],
            heat_request_entity=data["heat_request_entity"],
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via controller logic."""
        now = datetime.now(UTC)
        dt = CONTROLLER_LOOP_INTERVAL
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
        current_temp: float | None = None
        if temp_state is not None:
            try:
                current_temp = float(temp_state.state)
            except (ValueError, TypeError):
                LOGGER.warning(
                    "Invalid temperature state for %s: %s",
                    runtime.config.temp_sensor,
                    temp_state.state,
                )

        # Update PID controller
        self._controller.update_zone_pid(zone_id, current_temp, dt)

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

        # Update zone with historical data
        self._controller.update_zone_historical(
            zone_id,
            duty_cycle_avg=runtime.state.duty_cycle,  # Current duty cycle
            period_state_avg=period_state_avg,
            open_state_avg=open_state_avg,
            window_open_avg=window_open_avg,
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
        """Execute heat request by calling switch service."""
        entity_id = self._controller.config.heat_request_entity
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
            state = self._controller.get_zone_state(zone_id)
            if state is not None:
                result["zones"][zone_id] = {
                    "current_temp": state.current_temp,
                    "setpoint": state.setpoint,
                    "duty_cycle": state.duty_cycle,
                    "error": state.error,
                    "integral": state.integral,
                    "valve_on": state.valve_on,
                    "enabled": state.enabled,
                    "window_blocked": state.window_open_avg
                    > self._controller.config.timing.window_block_threshold,
                    "is_requesting_heat": state.valve_on
                    and state.open_state_avg >= _VALVE_OPEN_THRESHOLD,
                }

        return result

    def set_zone_setpoint(self, zone_id: str, setpoint: float) -> None:
        """Set zone setpoint and trigger update."""
        if self._controller.set_zone_setpoint(zone_id, setpoint):
            self.async_set_updated_data(self._build_state_dict())

    def set_zone_enabled(self, zone_id: str, *, enabled: bool) -> None:
        """Enable or disable a zone and trigger update."""
        if self._controller.set_zone_enabled(zone_id, enabled=enabled):
            self.async_set_updated_data(self._build_state_dict())

    def set_mode(self, mode: str) -> None:
        """Set controller operation mode and trigger update."""
        self._controller.mode = mode
        self.async_set_updated_data(self._build_state_dict())
