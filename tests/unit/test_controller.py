"""Test heating controller core logic."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ufh_controller.const import (
    OperationMode,
    SummerMode,
    TimingConfig,
    ValveState,
    ZoneStatus,
)
from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    HeatingController,
    ZoneConfig,
)
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
)
from tests.conftest import setup_zone_historical, setup_zone_pid

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def basic_config() -> ControllerConfig:
    """Create a basic controller configuration with two zones."""
    return ControllerConfig(
        controller_id="heating",
        name="Heating Controller",
        zones=[
            ZoneConfig(
                zone_id="living_room",
                name="Living Room",
                temp_sensor="sensor.living_room_temp",
                valve_switch="switch.living_room_valve",
            ),
            ZoneConfig(
                zone_id="bedroom",
                name="Bedroom",
                temp_sensor="sensor.bedroom_temp",
                valve_switch="switch.bedroom_valve",
            ),
        ],
    )


@pytest.fixture
def flush_config() -> ControllerConfig:
    """Create a controller configuration with flush circuit."""
    return ControllerConfig(
        controller_id="heating",
        name="Heating Controller",
        zones=[
            ZoneConfig(
                zone_id="living_room",
                name="Living Room",
                temp_sensor="sensor.living_room_temp",
                valve_switch="switch.living_room_valve",
                circuit_type=CircuitType.REGULAR,
            ),
            ZoneConfig(
                zone_id="bathroom",
                name="Bathroom",
                temp_sensor="sensor.bathroom_temp",
                valve_switch="switch.bathroom_valve",
                circuit_type=CircuitType.FLUSH,
            ),
        ],
    )


class TestHeatingControllerInit:
    """Test HeatingController initialization."""

    def test_init_with_zones(self, basic_config: ControllerConfig) -> None:
        """Test controller initializes with zones."""
        controller = HeatingController(basic_config, started_at=NOW)

        assert len(controller.zone_ids) == 2
        assert "living_room" in controller.zone_ids
        assert "bedroom" in controller.zone_ids

    def test_init_default_mode(self, basic_config: ControllerConfig) -> None:
        """Test controller starts in heat mode."""
        controller = HeatingController(basic_config, started_at=NOW)
        assert controller.mode == OperationMode.HEAT

    def test_init_zone_state(self, basic_config: ControllerConfig) -> None:
        """Test zone state is initialized correctly."""
        controller = HeatingController(basic_config, started_at=NOW)

        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.zone_id == "living_room"
        assert state.setpoint == 21.0
        assert state.valve_state == ValveState.UNKNOWN
        assert state.enabled is True


class TestModeProperty:
    """Test mode property."""

    def test_get_mode(self, basic_config: ControllerConfig) -> None:
        """Test getting mode."""
        controller = HeatingController(basic_config, started_at=NOW)
        assert controller.mode == OperationMode.HEAT

    def test_set_mode(self, basic_config: ControllerConfig) -> None:
        """Test setting mode."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.mode = OperationMode.FLUSH
        assert controller.mode == OperationMode.FLUSH


class TestSetZoneSetpoint:
    """Test set_zone_setpoint method."""

    def test_set_valid_setpoint(self, basic_config: ControllerConfig) -> None:
        """Test setting a valid setpoint."""
        controller = HeatingController(basic_config, started_at=NOW)
        result = controller.set_zone_setpoint("living_room", 22.0)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.setpoint == 22.0

    def test_set_setpoint_clamped_high(self, basic_config: ControllerConfig) -> None:
        """Test setpoint clamped to max."""
        controller = HeatingController(basic_config, started_at=NOW)
        result = controller.set_zone_setpoint("living_room", 35.0)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.setpoint == 28.0  # Default max

    def test_set_setpoint_clamped_low(self, basic_config: ControllerConfig) -> None:
        """Test setpoint clamped to min."""
        controller = HeatingController(basic_config, started_at=NOW)
        result = controller.set_zone_setpoint("living_room", 10.0)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.setpoint == 16.0  # Default min

    def test_set_setpoint_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test setting setpoint for unknown zone."""
        controller = HeatingController(basic_config, started_at=NOW)
        result = controller.set_zone_setpoint("unknown", 22.0)
        assert result is False


class TestSetZoneEnabled:
    """Test set_zone_enabled method."""

    def test_disable_zone(self, basic_config: ControllerConfig) -> None:
        """Test disabling a zone."""
        controller = HeatingController(basic_config, started_at=NOW)
        result = controller.set_zone_enabled("living_room", enabled=False)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.enabled is False

    def test_enable_zone(self, basic_config: ControllerConfig) -> None:
        """Test enabling a zone."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.set_zone_enabled("living_room", enabled=False)
        result = controller.set_zone_enabled("living_room", enabled=True)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.enabled is True

    def test_enable_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test enabling unknown zone."""
        controller = HeatingController(basic_config, started_at=NOW)
        result = controller.set_zone_enabled("unknown", enabled=True)
        assert result is False


class TestUpdateZonePID:
    """Test update_zone_pid method."""

    def test_update_with_temperature(self, basic_config: ControllerConfig) -> None:
        """Test PID update with temperature reading."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.set_zone_setpoint("living_room", 22.0)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)

        # With 2 degree error and Kp=50, expect significant duty cycle
        runtime = controller.get_zone_runtime("living_room")
        assert runtime.pid.state is not None
        assert runtime.pid.state.duty_cycle > 0.0
        assert runtime.state.current == 20.0

    def test_update_with_none_temperature(self, basic_config: ControllerConfig) -> None:
        """Test PID update with no temperature reading."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update with valid temp
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime.pid.state is not None
        first_duty = runtime.pid.state.duty_cycle

        # Update with None - should maintain duty cycle
        setup_zone_pid(controller, "living_room", None, 60.0)
        assert runtime.pid.state.duty_cycle == first_duty

    def test_update_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test PID update for unknown zone raises KeyError."""
        controller = HeatingController(basic_config, started_at=NOW)
        with pytest.raises(KeyError):
            setup_zone_pid(controller, "unknown", 20.0, 60.0)


class TestPIDIntegrationPause:
    """Test PID integration pausing when zone is blocked."""

    def test_pid_paused_in_all_off_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is all_off."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update in heat mode to establish baseline integral
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        # Switch to all_off mode
        controller.mode = OperationMode.ALL_OFF

        # PID update should NOT accumulate integral
        setup_zone_pid(controller, "living_room", 19.0, 60.0)  # Larger error

        # Integral should remain unchanged (paused)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_paused_in_flush_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is flush."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update in heat mode
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        # Switch to flush mode
        controller.mode = OperationMode.FLUSH

        # PID update should NOT accumulate integral
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_paused_in_all_on_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is all_on."""
        controller = HeatingController(basic_config, started_at=NOW)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        controller.mode = OperationMode.ALL_ON
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_paused_in_off_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is off."""
        controller = HeatingController(basic_config, started_at=NOW)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        controller.mode = OperationMode.OFF
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_paused_in_cycle_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is cycle."""
        controller = HeatingController(basic_config, started_at=NOW)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        controller.mode = OperationMode.CYCLE
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_paused_when_zone_disabled(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID integration is paused when zone is disabled."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update with zone enabled
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        # Disable the zone
        controller.set_zone_enabled("living_room", enabled=False)

        # PID update should NOT accumulate integral
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_paused_when_paused(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when window was recently open."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update with no recent window activity
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        # Simulate window was recently open (within blocking period)
        runtime.state.window = True

        # PID update should NOT accumulate integral
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral

    def test_pid_not_paused_when_window_not_recently_open(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID integration continues when window was not recently open."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        # No recent window activity
        runtime.state.window = False

        # PID update SHOULD accumulate integral
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral > initial_integral

    def test_pid_runs_normally_in_heat_mode(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID runs normally in heat mode with enabled zone and closed window."""
        controller = HeatingController(basic_config, started_at=NOW)
        assert controller.mode == OperationMode.HEAT

        # First update
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral

        # Second update should accumulate integral
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral > initial_integral

    def test_pid_paused_maintains_duty_cycle(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test that duty cycle is maintained when PID is paused."""
        controller = HeatingController(basic_config, started_at=NOW)

        # Establish a duty cycle in auto mode
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_duty_cycle = runtime.pid.state.duty_cycle
        assert initial_duty_cycle is not None
        assert initial_duty_cycle > 0  # Should have some duty cycle from error

        # Switch to mode that pauses PID
        controller.mode = OperationMode.ALL_OFF

        # Update with different temperature - duty cycle should be maintained
        setup_zone_pid(controller, "living_room", 15.0, 60.0)
        assert runtime.pid.state is not None
        assert runtime.pid.state.duty_cycle == initial_duty_cycle

    def test_pid_paused_preserves_last_error(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test that error is preserved (not updated) when PID is paused."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.set_zone_setpoint("living_room", 22.0)

        # Establish state in auto mode
        setup_zone_pid(controller, "living_room", 20.0, 60.0)

        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        # Error from initial update: setpoint (22) - current (20) = 2
        assert runtime.pid.state.error == 2.0

        # Switch to mode that pauses PID
        controller.mode = OperationMode.ALL_OFF

        # Update with new temperature - PID is paused so state should not change
        setup_zone_pid(controller, "living_room", 18.0, 60.0)

        # Error should still reflect last PID calculation, not current temperature
        assert runtime.pid.state is not None
        assert runtime.pid.state.error == 2.0

    def test_pid_resumes_after_pause(self, basic_config: ControllerConfig) -> None:
        """Test that PID resumes accumulating integral after pause ends."""
        controller = HeatingController(basic_config, started_at=NOW)

        # Initial update in auto mode
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        integral_after_first = runtime.pid.state.integral

        # Pause by switching mode
        controller.mode = OperationMode.ALL_OFF
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        integral_while_paused = runtime.pid.state.integral
        assert integral_while_paused == integral_after_first

        # Resume by switching back to heat
        controller.mode = OperationMode.HEAT
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        assert runtime.pid.state is not None
        integral_after_resume = runtime.pid.state.integral

        # Integral should have increased after resuming
        assert integral_after_resume > integral_while_paused

    def test_pid_paused_with_none_temperature(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID is paused when temperature is unavailable."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First update with valid temp
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        initial_integral = runtime.pid.state.integral
        initial_duty_cycle = runtime.pid.state.duty_cycle

        # Update with None temperature
        setup_zone_pid(controller, "living_room", None, 60.0)

        # Integral should be unchanged, duty cycle maintained
        assert runtime.pid.state is not None
        assert runtime.pid.state.integral == initial_integral
        assert runtime.pid.state.duty_cycle == initial_duty_cycle


class TestUpdateZoneHistorical:
    """Test update_zone_historical method."""

    def test_update_historical_data(self, basic_config: ControllerConfig) -> None:
        """Test updating zone historical data sets flow state."""
        controller = HeatingController(basic_config, started_at=NOW)

        # Set duty cycle first
        setup_zone_pid(controller, "living_room", 20.0, 60.0)

        setup_zone_historical(
            controller,
            "living_room",
            open_state_avg=0.9,  # Above 0.85 threshold
            window=False,
        )

        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.open_state_avg == 0.9
        assert state.window is False
        # Flow is derived from open_state_avg >= 0.85
        assert state.flow is True

    def test_update_historical_sets_flow_false(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test that flow is False when valve not open long enough."""
        controller = HeatingController(basic_config, started_at=NOW)

        setup_zone_historical(
            controller,
            "living_room",
            open_state_avg=0.5,  # Below 0.85 threshold
            window=False,
        )

        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.flow is False

    def test_update_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test updating unknown zone raises KeyError."""
        controller = HeatingController(basic_config, started_at=NOW)
        with pytest.raises(KeyError):
            setup_zone_historical(
                controller,
                "unknown",
                open_state_avg=0.9,
                window=False,
            )

    def test_quota_based_evaluation_with_used_duration(
        self, basic_config: ControllerConfig
    ) -> None:
        """
        Test that quota-based evaluation uses used_duration correctly.

        used_duration is now an internal accumulator rather than being
        calculated from recorder data.
        """
        controller = HeatingController(basic_config, started_at=NOW)

        # Set up zone with high duty cycle
        setup_zone_pid(controller, "living_room", 19.0, 60.0)
        setup_zone_historical(
            controller,
            "living_room",
            open_state_avg=0.0,
            window=False,
        )

        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None

        # Update requested_duration from duty cycle
        runtime.update_requested_duration(7200)

        # Simulate some used_duration
        runtime.state.used_duration = 1440.0

        actions = controller.evaluate(now=datetime.now(UTC)).valve_actions

        # Zone should turn on because it still has quota remaining:
        # requested_duration ~ 7200s (100% duty), used_duration is 1440s,
        # so remaining quota (5760s) exceeds min_run_time (540s)
        assert actions["living_room"] == ZoneAction.TURN_ON


class TestHeatRequestFromEvaluate:
    """Test heat_request values returned by evaluate()."""

    def test_off_mode_no_action(self, basic_config: ControllerConfig) -> None:
        """Test off mode returns no heat request action (None)."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.mode = OperationMode.OFF
        actions = controller.evaluate(now=datetime.now(UTC))
        # Off mode: heat_request is None (no actions)
        assert actions.heat_request is None

    def test_all_off_mode_no_request(self, basic_config: ControllerConfig) -> None:
        """Test all_off mode returns heat_request=False."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.mode = OperationMode.ALL_OFF
        actions = controller.evaluate(now=datetime.now(UTC))
        assert actions.heat_request is False

    def test_all_on_mode_requests_heat(self, basic_config: ControllerConfig) -> None:
        """Test all_on mode returns heat_request=True."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.mode = OperationMode.ALL_ON
        actions = controller.evaluate(now=datetime.now(UTC))
        assert actions.heat_request is True

    def test_flush_mode_no_heat_request(self, basic_config: ControllerConfig) -> None:
        """Test flush mode returns heat_request=False."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.mode = OperationMode.FLUSH
        actions = controller.evaluate(now=datetime.now(UTC))
        assert actions.heat_request is False

    def test_heat_mode_with_valve_open_and_ready(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test heat mode returns heat_request=True when valve is open and ready."""
        controller = HeatingController(basic_config, started_at=NOW)

        # Set up zone with valve on and fully open
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_historical(
            controller,
            "living_room",
            open_state_avg=0.9,  # Above 0.85 threshold (sets flow=True)
            window=False,
        )
        # Manually set valve on and quota
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        runtime.state.valve_state = ValveState.ON
        runtime.state.requested_duration = 3600.0  # 1 hour
        runtime.state.used_duration = 0.0

        actions = controller.evaluate(now=datetime.now(UTC))
        assert actions.heat_request is True


class TestGetSummerModeValue:
    """Test get_summer_mode_value method."""

    def test_no_summer_mode_entity(self, basic_config: ControllerConfig) -> None:
        """Test returns None when no summer mode entity configured."""
        controller = HeatingController(basic_config, started_at=NOW)
        assert controller.get_summer_mode_value(heat_request=True) is None

    def test_off_mode_returns_none(self) -> None:
        """Test off mode returns None."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config, started_at=NOW)
        controller.mode = OperationMode.OFF
        assert controller.get_summer_mode_value(heat_request=True) is None

    def test_flush_mode_returns_summer(self) -> None:
        """Test flush mode returns summer."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config, started_at=NOW)
        controller.mode = OperationMode.FLUSH
        assert controller.get_summer_mode_value(heat_request=True) == SummerMode.SUMMER

    def test_all_off_mode_returns_summer(self) -> None:
        """Test all_off mode returns summer."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config, started_at=NOW)
        controller.mode = OperationMode.ALL_OFF
        assert controller.get_summer_mode_value(heat_request=False) == SummerMode.SUMMER

    def test_all_on_mode_returns_winter(self) -> None:
        """Test all_on mode returns winter."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config, started_at=NOW)
        controller.mode = OperationMode.ALL_ON
        assert controller.get_summer_mode_value(heat_request=True) == SummerMode.WINTER

    def test_heat_mode_with_heat_request(self) -> None:
        """Test heat mode with heat request returns winter."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config, started_at=NOW)
        assert controller.get_summer_mode_value(heat_request=True) == SummerMode.WINTER

    def test_heat_mode_without_heat_request(self) -> None:
        """Test heat mode without heat request returns summer."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config, started_at=NOW)
        assert controller.get_summer_mode_value(heat_request=False) == SummerMode.SUMMER


class TestComputeActionsWithFlushZones:
    """Test compute_actions method with flush circuit zones."""

    def test_evaluate_includes_flush_zone_actions(
        self, flush_config: ControllerConfig
    ) -> None:
        """Test that evaluate() returns actions for flush zones."""
        controller = HeatingController(flush_config, started_at=NOW)

        # Set up both zones with PID data
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_pid(controller, "bathroom", 22.0, 60.0)

        # Set up historical data for both zones
        setup_zone_historical(
            controller,
            "living_room",
            open_state_avg=0.0,
            window=False,
        )
        setup_zone_historical(
            controller,
            "bathroom",
            open_state_avg=0.0,
            window=False,
        )

        actions = controller.evaluate(now=datetime.now(UTC))

        # Both zones should have actions computed
        assert "living_room" in actions.valve_actions
        assert "bathroom" in actions.valve_actions

    def test_flush_zone_receives_flush_request(
        self, flush_config: ControllerConfig
    ) -> None:
        """Test that flush zone evaluation receives flush_request parameter."""
        controller = HeatingController(flush_config, started_at=NOW)

        # Enable flush
        controller.state.flush_enabled = True

        # Set up zones
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_pid(controller, "bathroom", 22.0, 60.0)

        # Set up historical data with no regular zones running
        setup_zone_historical(
            controller,
            "living_room",
            open_state_avg=0.0,
            window=False,
        )
        setup_zone_historical(
            controller,
            "bathroom",
            open_state_avg=0.0,
            window=False,
        )

        actions = controller.evaluate(now=datetime.now(UTC))

        # Flush zone should be in valve_actions (was evaluated via phase 3)
        assert "bathroom" in actions.valve_actions


class TestAnyZoneInFailSafe:
    """Test any_zone_in_fail_safe property."""

    def test_no_zones_in_fail_safe(self, basic_config: ControllerConfig) -> None:
        """Test returns False when no zones are in fail-safe."""
        controller = HeatingController(basic_config, started_at=NOW)
        assert controller.any_zone_in_fail_safe is False

    def test_one_zone_in_fail_safe(self, basic_config: ControllerConfig) -> None:
        """Test returns True when one zone is in fail-safe."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.get_zone_state("living_room").zone_status = ZoneStatus.FAIL_SAFE
        assert controller.any_zone_in_fail_safe is True

    def test_all_zones_in_fail_safe(self, basic_config: ControllerConfig) -> None:
        """Test returns True when all zones are in fail-safe."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.get_zone_state("living_room").zone_status = ZoneStatus.FAIL_SAFE
        controller.get_zone_state("bedroom").zone_status = ZoneStatus.FAIL_SAFE
        assert controller.any_zone_in_fail_safe is True


class TestUpdateDhwState:
    """Test update_dhw_state method."""

    def test_off_to_on_clears_flush_until(self, basic_config: ControllerConfig) -> None:
        """Test OFF→ON transition clears flush_until."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.state.flush_until = NOW + timedelta(seconds=480)

        controller.update_dhw_state(dhw_active=True, now=NOW)

        assert controller.state.flush_until is None
        assert controller.state.dhw_active is True

    def test_on_to_off_sets_flush_until_when_enabled(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test ON→OFF sets flush_until when flush enabled and duration > 0."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.state.dhw_active = True
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=False, now=NOW)

        flush_duration = controller.config.timing.flush_duration
        assert controller.state.flush_until == NOW + timedelta(seconds=flush_duration)
        assert controller.state.dhw_active is False

    def test_on_to_off_no_flush_when_disabled(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test ON→OFF does NOT set flush_until when flush disabled."""
        controller = HeatingController(basic_config, started_at=NOW)
        controller.state.dhw_active = True
        controller.state.flush_enabled = False

        controller.update_dhw_state(dhw_active=False, now=NOW)

        assert controller.state.flush_until is None

    def test_on_to_off_no_flush_when_duration_zero(self) -> None:
        """Test ON→OFF does NOT set flush_until when duration is 0."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            zones=[],
            timing=TimingConfig(flush_duration=0),
        )
        controller = HeatingController(config, started_at=NOW)
        controller.state.dhw_active = True
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=False, now=NOW)

        assert controller.state.flush_until is None

    def test_same_state_no_change(self, basic_config: ControllerConfig) -> None:
        """Test no transition (same state) doesn't change flush_until."""
        controller = HeatingController(basic_config, started_at=NOW)
        existing_flush_until = NOW + timedelta(seconds=100)
        controller.state.flush_until = existing_flush_until

        # OFF→OFF: no transition
        controller.update_dhw_state(dhw_active=False, now=NOW)

        assert controller.state.flush_until == existing_flush_until


class TestHandleObservationPeriodTransition:
    """Test handle_observation_period_transition method."""

    def test_first_call_returns_true(self, basic_config: ControllerConfig) -> None:
        """Test first call (last_force_update=None) returns True."""
        controller = HeatingController(basic_config, started_at=NOW)
        assert controller.state.last_force_update is None

        result = controller.handle_observation_period_transition(NOW)

        assert result is True
        assert controller.state.last_force_update == NOW

    def test_first_call_resets_used_duration(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test first call resets used_duration for all zones."""
        controller = HeatingController(basic_config, started_at=NOW)

        # Set some used_duration on zones
        for zone_id in controller.zone_ids:
            controller.get_zone_runtime(zone_id).state.used_duration = 500.0

        controller.handle_observation_period_transition(NOW)

        for zone_id in controller.zone_ids:
            rt = controller.get_zone_runtime(zone_id)
            assert rt.state.used_duration == 0.0

    def test_same_period_returns_false(self, basic_config: ControllerConfig) -> None:
        """Test same period returns False and does not reset used_duration."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First call to establish period
        controller.handle_observation_period_transition(NOW)

        # Set used_duration after period established
        for zone_id in controller.zone_ids:
            controller.get_zone_runtime(zone_id).state.used_duration = 500.0

        # Second call within same period
        same_period_time = NOW + timedelta(seconds=60)
        result = controller.handle_observation_period_transition(same_period_time)

        assert result is False
        # used_duration should NOT be reset
        for zone_id in controller.zone_ids:
            rt = controller.get_zone_runtime(zone_id)
            assert rt.state.used_duration == 500.0

    def test_new_period_returns_true(self, basic_config: ControllerConfig) -> None:
        """Test new period boundary returns True and resets used_duration."""
        controller = HeatingController(basic_config, started_at=NOW)

        # First call at noon
        controller.handle_observation_period_transition(NOW)

        # Set used_duration
        for zone_id in controller.zone_ids:
            controller.get_zone_runtime(zone_id).state.used_duration = 500.0

        # Move to next observation period (default 7200s = 2h)
        next_period = NOW + timedelta(seconds=7200)
        result = controller.handle_observation_period_transition(next_period)

        assert result is True
        for zone_id in controller.zone_ids:
            rt = controller.get_zone_runtime(zone_id)
            assert rt.state.used_duration == 0.0

    def test_updates_observation_start_and_elapsed(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test observation_start and period_elapsed are updated."""
        controller = HeatingController(basic_config, started_at=NOW)

        # NOW is 12:00:00, so observation_start should be 12:00:00
        controller.handle_observation_period_transition(NOW)

        assert controller.state.observation_start == NOW
        assert controller.state.period_elapsed == 0.0

        # 30 minutes into the period
        later = NOW + timedelta(minutes=30)
        controller.handle_observation_period_transition(later)

        assert controller.state.observation_start == NOW
        assert controller.state.period_elapsed == pytest.approx(1800.0)
