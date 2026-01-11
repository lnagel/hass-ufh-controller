"""Test heating controller logic."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    SummerMode,
    ValveState,
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
        controller = HeatingController(basic_config)

        assert len(controller.zone_ids) == 2
        assert "living_room" in controller.zone_ids
        assert "bedroom" in controller.zone_ids

    def test_init_default_mode(self, basic_config: ControllerConfig) -> None:
        """Test controller starts in auto mode."""
        controller = HeatingController(basic_config)
        assert controller.mode == "auto"

    def test_init_zone_state(self, basic_config: ControllerConfig) -> None:
        """Test zone state is initialized correctly."""
        controller = HeatingController(basic_config)

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
        controller = HeatingController(basic_config)
        assert controller.mode == "auto"

    def test_set_mode(self, basic_config: ControllerConfig) -> None:
        """Test setting mode."""
        controller = HeatingController(basic_config)
        controller.mode = "flush"
        assert controller.mode == "flush"


class TestSetZoneSetpoint:
    """Test set_zone_setpoint method."""

    def test_set_valid_setpoint(self, basic_config: ControllerConfig) -> None:
        """Test setting a valid setpoint."""
        controller = HeatingController(basic_config)
        result = controller.set_zone_setpoint("living_room", 22.0)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.setpoint == 22.0

    def test_set_setpoint_clamped_high(self, basic_config: ControllerConfig) -> None:
        """Test setpoint clamped to max."""
        controller = HeatingController(basic_config)
        result = controller.set_zone_setpoint("living_room", 35.0)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.setpoint == 28.0  # Default max

    def test_set_setpoint_clamped_low(self, basic_config: ControllerConfig) -> None:
        """Test setpoint clamped to min."""
        controller = HeatingController(basic_config)
        result = controller.set_zone_setpoint("living_room", 10.0)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.setpoint == 16.0  # Default min

    def test_set_setpoint_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test setting setpoint for unknown zone."""
        controller = HeatingController(basic_config)
        result = controller.set_zone_setpoint("unknown", 22.0)
        assert result is False


class TestSetZoneEnabled:
    """Test set_zone_enabled method."""

    def test_disable_zone(self, basic_config: ControllerConfig) -> None:
        """Test disabling a zone."""
        controller = HeatingController(basic_config)
        result = controller.set_zone_enabled("living_room", enabled=False)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.enabled is False

    def test_enable_zone(self, basic_config: ControllerConfig) -> None:
        """Test enabling a zone."""
        controller = HeatingController(basic_config)
        controller.set_zone_enabled("living_room", enabled=False)
        result = controller.set_zone_enabled("living_room", enabled=True)

        assert result is True
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.enabled is True

    def test_enable_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test enabling unknown zone."""
        controller = HeatingController(basic_config)
        result = controller.set_zone_enabled("unknown", enabled=True)
        assert result is False


class TestUpdateZonePID:
    """Test update_zone_pid method."""

    def test_update_with_temperature(self, basic_config: ControllerConfig) -> None:
        """Test PID update with temperature reading."""
        controller = HeatingController(basic_config)
        controller.set_zone_setpoint("living_room", 22.0)

        duty_cycle = controller.update_zone_pid("living_room", 20.0, 60.0)

        # With 2 degree error and Kp=50, expect significant duty cycle
        assert duty_cycle is not None
        assert duty_cycle > 0.0
        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.current == 20.0
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        assert runtime.pid.state.duty_cycle == duty_cycle

    def test_update_with_none_temperature(self, basic_config: ControllerConfig) -> None:
        """Test PID update with no temperature reading."""
        controller = HeatingController(basic_config)

        # First update with valid temp
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None
        first_duty = runtime.pid.state.duty_cycle

        # Update with None - should maintain duty cycle
        duty_cycle = controller.update_zone_pid("living_room", None, 60.0)
        assert duty_cycle == first_duty

    def test_update_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test PID update for unknown zone."""
        controller = HeatingController(basic_config)
        duty_cycle = controller.update_zone_pid("unknown", 20.0, 60.0)
        assert duty_cycle == 0.0


class TestPIDIntegrationPause:
    """Test PID integration pausing when zone is blocked."""

    def test_pid_paused_in_all_off_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is all_off."""
        controller = HeatingController(basic_config)

        # First update in auto mode to establish baseline integral
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        # Switch to all_off mode
        controller.mode = "all_off"

        # PID update should NOT accumulate integral
        controller.update_zone_pid("living_room", 19.0, 60.0)  # Larger error

        # Integral should remain unchanged (paused)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_paused_in_flush_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is flush."""
        controller = HeatingController(basic_config)

        # First update in auto mode
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        # Switch to flush mode
        controller.mode = "flush"

        # PID update should NOT accumulate integral
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_paused_in_all_on_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is all_on."""
        controller = HeatingController(basic_config)

        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        controller.mode = "all_on"
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_paused_in_disabled_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is disabled."""
        controller = HeatingController(basic_config)

        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        controller.mode = "disabled"
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_paused_in_cycle_mode(self, basic_config: ControllerConfig) -> None:
        """Test PID integration is paused when mode is cycle."""
        controller = HeatingController(basic_config)

        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        controller.mode = "cycle"
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_paused_when_zone_disabled(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID integration is paused when zone is disabled."""
        controller = HeatingController(basic_config)

        # First update with zone enabled
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        # Disable the zone
        controller.set_zone_enabled("living_room", enabled=False)

        # PID update should NOT accumulate integral
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_paused_when_window_recently_open(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID integration is paused when window was recently open."""
        controller = HeatingController(basic_config)

        # First update with no recent window activity
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        # Simulate window was recently open (within blocking period)
        runtime.state.window_recently_open = True

        # PID update should NOT accumulate integral
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term == initial_integral

    def test_pid_not_paused_when_window_not_recently_open(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID integration continues when window was not recently open."""
        controller = HeatingController(basic_config)

        # First update
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        # No recent window activity
        runtime.state.window_recently_open = False

        # PID update SHOULD accumulate integral
        controller.update_zone_pid("living_room", 19.0, 60.0)
        assert runtime.pid.state.i_term > initial_integral

    def test_pid_runs_normally_in_auto_mode(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID runs normally in auto mode with enabled zone and closed window."""
        controller = HeatingController(basic_config)
        assert controller.mode == "auto"

        # First update
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term

        # Second update should accumulate integral
        controller.update_zone_pid("living_room", 20.0, 60.0)
        assert runtime.pid.state.i_term > initial_integral

    def test_pid_paused_maintains_duty_cycle(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test that duty cycle is maintained when PID is paused."""
        controller = HeatingController(basic_config)

        # Establish a duty cycle in auto mode
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_duty_cycle = runtime.pid.state.duty_cycle
        assert initial_duty_cycle is not None
        assert initial_duty_cycle > 0  # Should have some duty cycle from error

        # Switch to mode that pauses PID
        controller.mode = "all_off"

        # Update with different temperature - duty cycle should be maintained
        returned_duty = controller.update_zone_pid("living_room", 15.0, 60.0)
        assert returned_duty == initial_duty_cycle
        assert runtime.pid.state.duty_cycle == initial_duty_cycle

    def test_pid_paused_updates_error_for_display(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test that error is still updated when PID is paused (for UI display)."""
        controller = HeatingController(basic_config)
        controller.set_zone_setpoint("living_room", 22.0)

        # Establish state in auto mode
        controller.update_zone_pid("living_room", 20.0, 60.0)

        # Switch to mode that pauses PID
        controller.mode = "all_off"

        # Update with new temperature
        controller.update_zone_pid("living_room", 18.0, 60.0)

        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        # Error should reflect current state: setpoint (22) - current (18) = 4
        assert runtime.pid.state.error == 4.0

    def test_pid_resumes_after_pause(self, basic_config: ControllerConfig) -> None:
        """Test that PID resumes accumulating integral after pause ends."""
        controller = HeatingController(basic_config)

        # Initial update in auto mode
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        integral_after_first = runtime.pid.state.i_term

        # Pause by switching mode
        controller.mode = "all_off"
        controller.update_zone_pid("living_room", 19.0, 60.0)
        integral_while_paused = runtime.pid.state.i_term
        assert integral_while_paused == integral_after_first

        # Resume by switching back to auto
        controller.mode = "auto"
        controller.update_zone_pid("living_room", 19.0, 60.0)
        integral_after_resume = runtime.pid.state.i_term

        # Integral should have increased after resuming
        assert integral_after_resume > integral_while_paused

    def test_pid_paused_with_none_temperature(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test PID is paused when temperature is unavailable."""
        controller = HeatingController(basic_config)

        # First update with valid temp
        controller.update_zone_pid("living_room", 20.0, 60.0)
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        initial_integral = runtime.pid.state.i_term
        initial_duty_cycle = runtime.pid.state.duty_cycle

        # Update with None temperature
        returned_duty = controller.update_zone_pid("living_room", None, 60.0)

        # Integral should be unchanged, duty cycle maintained
        assert runtime.pid.state.i_term == initial_integral
        assert returned_duty == initial_duty_cycle


class TestUpdateZoneHistorical:
    """Test update_zone_historical method."""

    def test_update_historical_data(self, basic_config: ControllerConfig) -> None:
        """Test updating zone historical data."""
        controller = HeatingController(basic_config)

        # Set duty cycle first
        controller.update_zone_pid("living_room", 20.0, 60.0)

        controller.update_zone_historical(
            "living_room",
            period_state_avg=0.25,
            open_state_avg=0.9,
            window_recently_open=False,
            elapsed_time=7200.0,  # Full observation period
        )

        state = controller.get_zone_state("living_room")
        assert state is not None
        assert state.period_state_avg == 0.25
        assert state.open_state_avg == 0.9
        assert state.window_recently_open is False
        # Used duration = 0.25 * 7200 = 1800
        assert state.used_duration == 1800.0

    def test_update_unknown_zone(self, basic_config: ControllerConfig) -> None:
        """Test updating unknown zone does nothing."""
        controller = HeatingController(basic_config)
        # Should not raise
        controller.update_zone_historical(
            "unknown",
            period_state_avg=0.25,
            open_state_avg=0.9,
            window_recently_open=False,
            elapsed_time=7200.0,
        )

    def test_used_duration_with_elapsed_time(
        self, basic_config: ControllerConfig
    ) -> None:
        """
        Test used_duration calculation uses elapsed time, not full period.

        When partway through an observation period, used_duration should be
        calculated from the actual elapsed time, not the full observation period.
        """
        controller = HeatingController(basic_config)

        # Set duty cycle to 90%
        controller.update_zone_pid("living_room", 19.0, 60.0)  # 2 degree error

        # Simulate being 30 minutes (1800s) into a 2-hour observation period
        # Valve was on 50% of the elapsed time (15 minutes = 900 seconds)
        controller.update_zone_historical(
            "living_room",
            period_state_avg=0.5,  # On 50% of elapsed time
            open_state_avg=0.9,
            window_recently_open=False,
            elapsed_time=1800.0,
        )

        state = controller.get_zone_state("living_room")
        assert state is not None
        # used_duration should be 0.5 * 1800 = 900 seconds (NOT 0.5 * 7200 = 3600)
        assert state.used_duration == 900.0
        # requested_duration still uses full period: duty_cycle * 7200
        # With 2 degree error and Kp=50, duty_cycle ≈ 100% (clamped)
        assert state.requested_duration > 0

    def test_high_duty_cycle_low_elapsed_time_turns_on(
        self, basic_config: ControllerConfig
    ) -> None:
        """
        Test that high duty cycle zone turns on even early in observation period.

        This is a regression test for the bug where used_duration was incorrectly
        calculated using full period instead of elapsed time, causing zones to
        think they had used more quota than they actually had.
        """
        controller = HeatingController(basic_config)

        # Set up zone with high duty cycle (90%)
        controller.update_zone_pid("living_room", 19.0, 60.0)

        # Early in observation period (30 min), valve was on most of the time (80%)
        # Bug: used_duration = 0.8 * 7200 = 5760 (would exceed quota for 80% duty)
        # Fix: used_duration = 0.8 * 1800 = 1440 (still has plenty of quota)
        controller.update_zone_historical(
            "living_room",
            period_state_avg=0.8,
            open_state_avg=0.0,
            window_recently_open=False,
            elapsed_time=1800.0,
        )

        actions = controller.evaluate_zones()

        # Zone should turn on because it still has quota remaining:
        # With 100% duty cycle: requested_duration is 7200s, used_duration is 1440s,
        # so remaining quota (5760s) exceeds min_run_time (540s)
        assert actions["living_room"] == ZoneAction.TURN_ON


class TestEvaluateZonesAutoMode:
    """Test evaluate_zones in auto mode."""

    def test_zone_with_quota_turns_on(self, basic_config: ControllerConfig) -> None:
        """Test zone with remaining quota turns on."""
        controller = HeatingController(basic_config)

        # Set up zone with duty cycle and unused quota
        controller.update_zone_pid("living_room", 20.0, 60.0)
        controller.update_zone_historical(
            "living_room",
            period_state_avg=0.0,  # No usage yet
            open_state_avg=0.0,
            window_recently_open=False,
            elapsed_time=7200.0,  # Full observation period
        )

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.TURN_ON

    def test_disabled_zone_turns_off(self, basic_config: ControllerConfig) -> None:
        """Test disabled zone with unknown valve state emits TURN_OFF."""
        controller = HeatingController(basic_config)
        controller.set_zone_enabled("living_room", enabled=False)

        actions = controller.evaluate_zones()

        # Valve state is UNKNOWN by default, so actively turn off
        assert actions["living_room"] == ZoneAction.TURN_OFF

    def test_disabled_zone_confirmed_off_stays_off(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test disabled zone with confirmed OFF valve stays off."""
        controller = HeatingController(basic_config)
        controller.set_zone_enabled("living_room", enabled=False)
        zone_state = controller.get_zone_state("living_room")
        assert zone_state is not None
        zone_state.valve_state = ValveState.OFF

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_OFF


class TestEvaluateZonesAllOnMode:
    """Test evaluate_zones in all_on mode."""

    def test_all_valves_turn_on(self, basic_config: ControllerConfig) -> None:
        """Test all valves turn on in all_on mode."""
        controller = HeatingController(basic_config)
        controller.mode = "all_on"

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.TURN_ON
        assert actions["bedroom"] == ZoneAction.TURN_ON

    def test_valve_stays_on(self, basic_config: ControllerConfig) -> None:
        """Test valve that's already on stays on."""
        controller = HeatingController(basic_config)
        controller.mode = "all_on"

        # First evaluation turns on
        controller.evaluate_zones()

        # Second evaluation stays on
        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_ON


class TestEvaluateZonesAllOffMode:
    """Test evaluate_zones in all_off mode."""

    def test_all_valves_stay_off(self, basic_config: ControllerConfig) -> None:
        """Test all valves stay off in all_off mode."""
        controller = HeatingController(basic_config)
        controller.mode = "all_off"

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_OFF
        assert actions["bedroom"] == ZoneAction.STAY_OFF


class TestEvaluateZonesFlushMode:
    """Test evaluate_zones in flush mode."""

    def test_all_valves_turn_on(self, basic_config: ControllerConfig) -> None:
        """Test all valves turn on in flush mode."""
        controller = HeatingController(basic_config)
        controller.mode = "flush"

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.TURN_ON
        assert actions["bedroom"] == ZoneAction.TURN_ON


class TestEvaluateZonesDisabledMode:
    """Test evaluate_zones in disabled mode."""

    def test_valves_maintain_state(self, basic_config: ControllerConfig) -> None:
        """Test valves maintain state in disabled mode."""
        controller = HeatingController(basic_config)

        # Turn on a valve first
        controller.mode = "all_on"
        controller.evaluate_zones()

        # Switch to disabled
        controller.mode = "disabled"
        actions = controller.evaluate_zones()

        # Valves that were on stay on
        assert actions["living_room"] == ZoneAction.STAY_ON


class TestEvaluateZonesCycleMode:
    """Test evaluate_zones in cycle mode."""

    def test_cycle_mode_hour_0_all_off(self, basic_config: ControllerConfig) -> None:
        """Test all zones off during rest hour (hour 0)."""
        controller = HeatingController(basic_config)
        controller.mode = "cycle"

        with patch(
            "custom_components.ufh_controller.core.controller.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 0, 30, 0, tzinfo=UTC)
            mock_dt.UTC = UTC
            actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_OFF
        assert actions["bedroom"] == ZoneAction.STAY_OFF

    def test_cycle_mode_first_zone_active(self, basic_config: ControllerConfig) -> None:
        """Test first zone active during hour 1."""
        controller = HeatingController(basic_config)
        controller.mode = "cycle"

        with patch(
            "custom_components.ufh_controller.core.controller.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 1, 30, 0, tzinfo=UTC)
            mock_dt.UTC = UTC
            actions = controller.evaluate_zones()

        # First zone should be on, second should be off
        assert actions["living_room"] == ZoneAction.TURN_ON
        assert actions["bedroom"] == ZoneAction.STAY_OFF

    def test_cycle_mode_second_zone_active(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test second zone active during hour 2."""
        controller = HeatingController(basic_config)
        controller.mode = "cycle"

        with patch(
            "custom_components.ufh_controller.core.controller.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 2, 30, 0, tzinfo=UTC)
            mock_dt.UTC = UTC
            actions = controller.evaluate_zones()

        # Second zone should be on
        assert actions["living_room"] == ZoneAction.STAY_OFF
        assert actions["bedroom"] == ZoneAction.TURN_ON


class TestCalculateHeatRequest:
    """Test calculate_heat_request method."""

    def test_disabled_mode_no_request(self, basic_config: ControllerConfig) -> None:
        """Test disabled mode returns no heat request."""
        controller = HeatingController(basic_config)
        controller.mode = "disabled"
        assert controller.calculate_heat_request() is False

    def test_all_off_mode_no_request(self, basic_config: ControllerConfig) -> None:
        """Test all_off mode returns no heat request."""
        controller = HeatingController(basic_config)
        controller.mode = "all_off"
        assert controller.calculate_heat_request() is False

    def test_all_on_mode_requests_heat(self, basic_config: ControllerConfig) -> None:
        """Test all_on mode requests heat."""
        controller = HeatingController(basic_config)
        controller.mode = "all_on"
        assert controller.calculate_heat_request() is True

    def test_flush_mode_no_heat_request(self, basic_config: ControllerConfig) -> None:
        """Test flush mode doesn't request heat."""
        controller = HeatingController(basic_config)
        controller.mode = "flush"
        assert controller.calculate_heat_request() is False

    def test_auto_mode_with_valve_open_and_ready(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test auto mode requests heat when valve is open and ready."""
        controller = HeatingController(basic_config)

        # Set up zone with valve on and fully open
        controller.update_zone_pid("living_room", 20.0, 60.0)
        controller.update_zone_historical(
            "living_room",
            period_state_avg=0.0,
            open_state_avg=0.9,  # Above 0.85 threshold
            window_recently_open=False,
            elapsed_time=7200.0,  # Full observation period
        )
        # Manually set valve on
        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        runtime.state.valve_state = ValveState.ON
        runtime.state.requested_duration = 3600.0  # 1 hour
        runtime.state.used_duration = 0.0

        assert controller.calculate_heat_request() is True


class TestGetSummerModeValue:
    """Test get_summer_mode_value method."""

    def test_no_summer_mode_entity(self, basic_config: ControllerConfig) -> None:
        """Test returns None when no summer mode entity configured."""
        controller = HeatingController(basic_config)
        assert controller.get_summer_mode_value(heat_request=True) is None

    def test_disabled_mode_returns_none(self) -> None:
        """Test disabled mode returns None."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config)
        controller.mode = "disabled"
        assert controller.get_summer_mode_value(heat_request=True) is None

    def test_flush_mode_returns_summer(self) -> None:
        """Test flush mode returns summer."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config)
        controller.mode = "flush"
        assert controller.get_summer_mode_value(heat_request=True) == SummerMode.SUMMER

    def test_all_off_mode_returns_summer(self) -> None:
        """Test all_off mode returns summer."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config)
        controller.mode = "all_off"
        assert controller.get_summer_mode_value(heat_request=False) == SummerMode.SUMMER

    def test_all_on_mode_returns_winter(self) -> None:
        """Test all_on mode returns winter."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config)
        controller.mode = "all_on"
        assert controller.get_summer_mode_value(heat_request=True) == SummerMode.WINTER

    def test_auto_mode_with_heat_request(self) -> None:
        """Test auto mode with heat request returns winter."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config)
        assert controller.get_summer_mode_value(heat_request=True) == SummerMode.WINTER

    def test_auto_mode_without_heat_request(self) -> None:
        """Test auto mode without heat request returns summer."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            summer_mode_entity="select.boiler_summer",
            zones=[],
        )
        controller = HeatingController(config)
        assert controller.get_summer_mode_value(heat_request=False) == SummerMode.SUMMER


class TestZoneConfig:
    """Test ZoneConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        config = ZoneConfig(
            zone_id="test",
            name="Test Zone",
            temp_sensor="sensor.test_temp",
            valve_switch="switch.test_valve",
        )
        assert config.circuit_type == CircuitType.REGULAR
        assert config.setpoint_min == DEFAULT_SETPOINT["min"]
        assert config.setpoint_max == DEFAULT_SETPOINT["max"]
        assert config.setpoint_default == DEFAULT_SETPOINT["default"]
        assert config.kp == DEFAULT_PID["kp"]
        assert config.ki == DEFAULT_PID["ki"]

    def test_flush_circuit(self) -> None:
        """Test flush circuit configuration."""
        config = ZoneConfig(
            zone_id="bathroom",
            name="Bathroom",
            temp_sensor="sensor.bathroom_temp",
            valve_switch="switch.bathroom_valve",
            circuit_type=CircuitType.FLUSH,
        )
        assert config.circuit_type == CircuitType.FLUSH


class TestControllerConfig:
    """Test ControllerConfig dataclass."""

    def test_minimal_config(self) -> None:
        """Test minimal configuration."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
        )
        assert config.dhw_active_entity is None
        assert config.summer_mode_entity is None
        assert len(config.zones) == 0

    def test_with_optional_entities(self) -> None:
        """Test configuration with optional entities."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            dhw_active_entity="binary_sensor.dhw",
            summer_mode_entity="select.summer",
        )
        assert config.dhw_active_entity == "binary_sensor.dhw"
        assert config.summer_mode_entity == "select.summer"
