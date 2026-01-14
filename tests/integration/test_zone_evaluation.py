"""Test zone evaluation decision logic."""

import pytest

from custom_components.ufh_controller.const import TimingParams, ValveState
from custom_components.ufh_controller.core.controller import ControllerState
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
    ZoneState,
    evaluate_zone,
    should_request_heat,
)


class TestEvaluateZoneDisabled:
    """Test zone disabled behavior."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create default timing params."""
        return TimingParams()

    @pytest.fixture
    def controller(self) -> ControllerState:
        """Create default controller state."""
        return ControllerState()

    def test_disabled_zone_valve_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Disabled zone with valve off stays off."""
        zone = ZoneState(zone_id="test", enabled=False, valve_state=ValveState.OFF)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_disabled_zone_valve_on(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Disabled zone with valve on turns off."""
        zone = ZoneState(zone_id="test", enabled=False, valve_state=ValveState.ON)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_OFF

    @pytest.mark.parametrize(
        "valve_state", [ValveState.UNKNOWN, ValveState.UNAVAILABLE]
    )
    def test_disabled_zone_valve_unknown_turns_off(
        self,
        timing: TimingParams,
        controller: ControllerState,
        valve_state: ValveState,
    ) -> None:
        """Disabled zone with unknown/unavailable valve state emits TURN_OFF."""
        zone = ZoneState(zone_id="test", enabled=False, valve_state=valve_state)
        result = evaluate_zone(zone, controller, timing)
        # When valve state is uncertain, actively turn off to ensure safe state
        assert result == ZoneAction.TURN_OFF


class TestEvaluateZoneFlushCircuit:
    """Test flush circuit priority behavior."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create default timing params."""
        return TimingParams()

    def test_flush_during_dhw_no_regular_demand(self, timing: TimingParams) -> None:
        """Flush circuit turns on during DHW when no regular demand."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=True,
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing, flush_request=True)
        assert result == ZoneAction.TURN_ON

    def test_flush_during_dhw_stays_on(self, timing: TimingParams) -> None:
        """Flush circuit stays on during DHW."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.ON,
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=True,
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing, flush_request=True)
        assert result == ZoneAction.STAY_ON

    def test_flush_blocked_by_regular_valve_on(self, timing: TimingParams) -> None:
        """Flush circuit blocked when regular circuit valve is ON."""
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
            valve_state=ValveState.ON,  # Valve is actively running
            requested_duration=1000.0,
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=True,
            flush_request=False,
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )
        # Should fall through to normal quota logic (stays off with 0 quota)
        result = evaluate_zone(flush_zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_flush_not_blocked_by_regular_demand_only(
        self, timing: TimingParams
    ) -> None:
        """Flush circuit NOT blocked when regular has demand but valve is OFF."""
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
            valve_state=ValveState.OFF,  # Valve is OFF (due to DHW priority)
            requested_duration=1000.0,  # Has demand but not running
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=True,
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )
        result = evaluate_zone(flush_zone, controller, timing, flush_request=True)
        assert result == ZoneAction.TURN_ON

    def test_flush_disabled_no_priority(self, timing: TimingParams) -> None:
        """Flush circuit follows normal logic when flush disabled."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
            requested_duration=0.0,
        )
        controller = ControllerState(
            flush_enabled=False,
            dhw_active=True,
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF


class TestEvaluateZoneWindowBlocking:
    """Test that window state does NOT affect valve control."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params with 600 second (10 min) window block time."""
        return TimingParams(window_block_time=600)

    @pytest.fixture
    def controller(self) -> ControllerState:
        """Create default controller state."""
        return ControllerState()

    def test_window_recently_open_valve_follows_quota_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Window recently open doesn't block valve - follows quota (off case)."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            window_recently_open=True,
            requested_duration=1000.0,
            used_duration=0.0,  # Has quota
        )
        result = evaluate_zone(zone, controller, timing)
        # Valve should turn on based on quota, not blocked by window
        assert result == ZoneAction.TURN_ON

    def test_window_recently_open_valve_follows_quota_on(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Window recently open doesn't turn off valve - follows quota (on case)."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            window_recently_open=True,
            requested_duration=1000.0,
            used_duration=500.0,  # Still has quota
        )
        result = evaluate_zone(zone, controller, timing)
        # Valve should stay on based on quota
        assert result == ZoneAction.STAY_ON

    def test_window_recently_open_quota_met_turns_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """When quota met, valve turns off regardless of window state."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            window_recently_open=True,
            requested_duration=1000.0,
            used_duration=1000.0,  # Quota met
        )
        result = evaluate_zone(zone, controller, timing)
        # Valve should turn off because quota is met, not because of window
        assert result == ZoneAction.TURN_OFF

    def test_no_window_state_normal_operation(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """With no window activity, normal quota-based operation."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            window_recently_open=False,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON


class TestEvaluateZonePeriodEndFreeze:
    """Test period end freeze behavior to prevent valve cycling at boundaries."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params with 7200s period and 540s min run time."""
        return TimingParams(observation_period=7200, min_run_time=540)

    def test_near_period_end_valve_on_stays_on(self, timing: TimingParams) -> None:
        """Valve on stays on when near end of observation period."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            requested_duration=1000.0,
            used_duration=1000.0,  # Quota met, would normally turn off
        )
        # 7200 - 7000 = 200 seconds remaining, less than 540 min_run_time
        controller = ControllerState(period_elapsed=7000.0)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_ON

    def test_near_period_end_valve_off_stays_off(self, timing: TimingParams) -> None:
        """Valve off stays off when near end of observation period."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,  # Has quota, would normally turn on
        )
        # 7200 - 7000 = 200 seconds remaining, less than 540 min_run_time
        controller = ControllerState(period_elapsed=7000.0)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_enough_time_remaining_normal_behavior(self, timing: TimingParams) -> None:
        """Normal behavior when enough time remaining in period."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        # 7200 - 6000 = 1200 seconds remaining, more than 540 min_run_time
        controller = ControllerState(period_elapsed=6000.0)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON

    def test_exactly_at_threshold_normal_behavior(self, timing: TimingParams) -> None:
        """Normal behavior when exactly at min_run_time threshold."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        # 7200 - 6660 = 540 seconds remaining, exactly min_run_time
        controller = ControllerState(period_elapsed=6660.0)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON

    def test_one_second_below_threshold_freezes(self, timing: TimingParams) -> None:
        """Freeze behavior when just below threshold."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,  # Has quota, would normally turn on
        )
        # 7200 - 6661 = 539 seconds remaining, just below 540 min_run_time
        controller = ControllerState(period_elapsed=6661.0)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_period_freeze_with_window_recently_open(
        self, timing: TimingParams
    ) -> None:
        """Period freeze still applies even when window was recently open."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            window_recently_open=True,  # Window was recently open
            requested_duration=1000.0,
            used_duration=0.0,
        )
        # Near end of period - period freeze takes effect
        controller = ControllerState(period_elapsed=7000.0)
        result = evaluate_zone(zone, controller, timing)
        # Period freeze applies - valve stays on to avoid cycling
        assert result == ZoneAction.STAY_ON


class TestEvaluateZoneQuotaScheduling:
    """Test quota-based scheduling behavior."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params with 9 minute min run time."""
        return TimingParams(min_run_time=540)

    @pytest.fixture
    def controller(self) -> ControllerState:
        """Create default controller state."""
        return ControllerState()

    def test_quota_remaining_turns_on(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Zone with quota remaining turns on."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON

    def test_quota_remaining_stays_on(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Zone already on with quota stays on."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            requested_duration=1000.0,
            used_duration=500.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_ON

    def test_quota_too_small_stays_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Zone with quota less than min_run_time stays off."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=700.0,  # Only 300 remaining, less than 540
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_quota_met_turns_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Zone that met quota turns off."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            requested_duration=1000.0,
            used_duration=1000.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_OFF

    def test_quota_met_stays_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Zone that met quota stays off."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=1000.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_zero_quota_stays_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Zone with zero quota stays off."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,
            requested_duration=0.0,
            used_duration=0.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    @pytest.mark.parametrize(
        "valve_state", [ValveState.UNKNOWN, ValveState.UNAVAILABLE]
    )
    def test_quota_met_unknown_valve_turns_off(
        self,
        timing: TimingParams,
        controller: ControllerState,
        valve_state: ValveState,
    ) -> None:
        """Zone that met quota with unknown valve emits TURN_OFF."""
        zone = ZoneState(
            zone_id="test",
            valve_state=valve_state,
            requested_duration=1000.0,
            used_duration=1000.0,
        )
        result = evaluate_zone(zone, controller, timing)
        # When valve state is uncertain, actively turn off
        assert result == ZoneAction.TURN_OFF


class TestEvaluateZoneDHWBlocking:
    """Test DHW blocking for regular circuits."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create default timing params."""
        return TimingParams()

    def test_regular_blocked_during_dhw(self, timing: TimingParams) -> None:
        """Regular circuit blocked during DHW heating."""
        zone = ZoneState(
            zone_id="test",
            circuit_type=CircuitType.REGULAR,
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        controller = ControllerState(dhw_active=True)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_regular_runs_without_dhw(self, timing: TimingParams) -> None:
        """Regular circuit runs when DHW inactive."""
        zone = ZoneState(
            zone_id="test",
            circuit_type=CircuitType.REGULAR,
            valve_state=ValveState.OFF,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        controller = ControllerState(dhw_active=False)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON

    def test_regular_stays_on_during_dhw(self, timing: TimingParams) -> None:
        """Regular circuit already ON stays ON during DHW to circulate water."""
        zone = ZoneState(
            zone_id="test",
            circuit_type=CircuitType.REGULAR,
            valve_state=ValveState.ON,  # Already running
            requested_duration=1000.0,
            used_duration=100.0,  # Has remaining quota
        )
        controller = ControllerState(dhw_active=True)
        result = evaluate_zone(zone, controller, timing)
        # Valve should stay on to continue circulating water through the floor
        assert result == ZoneAction.STAY_ON

    def test_regular_turns_off_during_dhw_when_quota_exhausted(
        self, timing: TimingParams
    ) -> None:
        """Regular circuit turns OFF during DHW when quota is exhausted."""
        zone = ZoneState(
            zone_id="test",
            circuit_type=CircuitType.REGULAR,
            valve_state=ValveState.ON,  # Currently running
            requested_duration=1000.0,
            used_duration=1000.0,  # Quota exhausted
        )
        controller = ControllerState(dhw_active=True)
        result = evaluate_zone(zone, controller, timing)
        # Valve should turn off - quota exhaustion takes precedence
        assert result == ZoneAction.TURN_OFF


class TestShouldRequestHeat:
    """Test cases for should_request_heat."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params."""
        return TimingParams(closing_warning_duration=240)

    def test_valve_off_no_request(self, timing: TimingParams) -> None:
        """Valve off doesn't request heat."""
        zone = ZoneState(zone_id="test", valve_state=ValveState.OFF)
        result = should_request_heat(zone, timing)
        assert result is False

    def test_disabled_zone_no_request(self, timing: TimingParams) -> None:
        """Disabled zone doesn't request heat."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            enabled=False,
            open_state_avg=1.0,
            requested_duration=1000.0,
        )
        result = should_request_heat(zone, timing)
        assert result is False

    def test_valve_not_fully_open_no_request(self, timing: TimingParams) -> None:
        """Valve not fully open doesn't request heat."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            open_state_avg=0.50,  # Below 85% threshold
            requested_duration=1000.0,
            used_duration=0.0,
        )
        result = should_request_heat(zone, timing)
        assert result is False

    def test_valve_about_to_close_no_request(self, timing: TimingParams) -> None:
        """Valve about to close doesn't request heat."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            open_state_avg=1.0,
            requested_duration=1000.0,
            used_duration=900.0,  # Only 100 remaining, less than 240 warning
        )
        result = should_request_heat(zone, timing)
        assert result is False

    def test_valve_fully_open_requests_heat(self, timing: TimingParams) -> None:
        """Valve fully open with quota requests heat."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,
            open_state_avg=0.90,  # Above 85% threshold
            requested_duration=1000.0,
            used_duration=0.0,
        )
        result = should_request_heat(zone, timing)
        assert result is True
