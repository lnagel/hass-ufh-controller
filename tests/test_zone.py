"""Test zone state and decision logic."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ufh_controller.const import ValveState
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ControllerState,
    TimingParams,
    ZoneAction,
    ZoneState,
    aggregate_heat_request,
    calculate_requested_duration,
    evaluate_zone,
    is_flush_requested,
    should_request_heat,
)


class TestCalculateRequestedDuration:
    """Test cases for calculate_requested_duration."""

    def test_zero_duty_cycle(self) -> None:
        """Test zero duty cycle returns zero duration."""
        result = calculate_requested_duration(0.0, 7200)
        assert result == 0.0

    def test_full_duty_cycle(self) -> None:
        """Test 100% duty cycle returns full period."""
        result = calculate_requested_duration(100.0, 7200)
        assert result == 7200.0

    def test_half_duty_cycle(self) -> None:
        """Test 50% duty cycle returns half period."""
        result = calculate_requested_duration(50.0, 7200)
        assert result == 3600.0

    def test_fractional_duty_cycle(self) -> None:
        """Test fractional duty cycle."""
        result = calculate_requested_duration(25.5, 7200)
        assert result == pytest.approx(1836.0)


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
        result = evaluate_zone(zone, controller, timing)
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
        result = evaluate_zone(zone, controller, timing)
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
        # Flush should turn on - regular valve is OFF
        result = evaluate_zone(flush_zone, controller, timing)
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


class TestPeriodTransitionScenario:
    """
    Test behavior across observation period transitions.

    These tests verify the system handles period boundaries correctly,
    preventing rapid valve cycling while still providing fresh quota
    allocation in new periods.
    """

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params with 7200s period and 540s min run time."""
        return TimingParams(observation_period=7200, min_run_time=540)

    def test_high_quota_usage_near_period_end_freezes(
        self, timing: TimingParams
    ) -> None:
        """
        Zone at 90% quota near period end should freeze (valve off stays off).

        Scenario: 13:59:50, zone has used 6480/7200 seconds (90% of quota).
        Only 10 seconds remaining in period - freeze should be active.
        """
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,  # Valve is off
            requested_duration=7200.0,  # 100% duty cycle
            used_duration=6480.0,  # 90% used, 720s remaining quota
        )
        # 7200 - 7190 = 10 seconds remaining (simulates 13:59:50)
        controller = ControllerState(period_elapsed=7190.0)
        result = evaluate_zone(zone, controller, timing)
        # Freeze active: valve off stays off, even though quota remains
        assert result == ZoneAction.STAY_OFF

    def test_high_quota_usage_near_period_end_valve_on_stays_on(
        self, timing: TimingParams
    ) -> None:
        """Zone running near period end should stay on (freeze prevents cycling)."""
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.ON,  # Valve is running
            requested_duration=7200.0,  # 100% duty cycle
            used_duration=6480.0,  # 90% used
        )
        # Only 10 seconds remaining
        controller = ControllerState(period_elapsed=7190.0)
        result = evaluate_zone(zone, controller, timing)
        # Freeze active: valve on stays on
        assert result == ZoneAction.STAY_ON

    def test_fresh_period_allows_turn_on(self, timing: TimingParams) -> None:
        """
        After period reset, zone with demand gets fresh quota and can turn on.

        Scenario: 14:00:30 (30 seconds into new period).
        Zone had high usage last period, but now has fresh quota.
        """
        zone = ZoneState(
            zone_id="test",
            valve_state=ValveState.OFF,  # Valve is off after period reset
            requested_duration=3600.0,  # 50% duty cycle = 3600s quota
            used_duration=30.0,  # Only 30s used in new period
        )
        # Fresh period: only 30 seconds elapsed
        controller = ControllerState(period_elapsed=30.0)
        result = evaluate_zone(zone, controller, timing)
        # Normal quota logic: has plenty of quota, can turn on
        assert result == ZoneAction.TURN_ON

    def test_multiple_zones_can_turn_on_at_period_start(
        self, timing: TimingParams
    ) -> None:
        """
        Multiple zones with demand can all turn on at start of new period.

        This is expected behavior - zones are evaluated independently and
        each gets its fresh quota allocation.
        """
        zone1 = ZoneState(
            zone_id="zone1",
            valve_state=ValveState.OFF,
            requested_duration=3600.0,  # 50% duty cycle
            used_duration=60.0,  # 1 minute used
        )
        zone2 = ZoneState(
            zone_id="zone2",
            valve_state=ValveState.OFF,
            requested_duration=5400.0,  # 75% duty cycle
            used_duration=60.0,  # 1 minute used
        )
        controller = ControllerState(
            period_elapsed=60.0,
            zones={"zone1": zone1, "zone2": zone2},
        )

        result1 = evaluate_zone(zone1, controller, timing)
        result2 = evaluate_zone(zone2, controller, timing)

        # Both zones can turn on - this is intentional
        assert result1 == ZoneAction.TURN_ON
        assert result2 == ZoneAction.TURN_ON


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


class TestAggregateHeatRequest:
    """Test cases for aggregate_heat_request."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params."""
        return TimingParams()

    def test_no_zones_no_request(self, timing: TimingParams) -> None:
        """Empty zones dict returns no request."""
        result = aggregate_heat_request({}, timing)
        assert result is False

    def test_all_zones_off_no_request(self, timing: TimingParams) -> None:
        """All zones off returns no request."""
        zones = {
            "zone1": ZoneState(zone_id="zone1", valve_state=ValveState.OFF),
            "zone2": ZoneState(zone_id="zone2", valve_state=ValveState.OFF),
        }
        result = aggregate_heat_request(zones, timing)
        assert result is False

    def test_one_zone_requesting(self, timing: TimingParams) -> None:
        """One zone requesting returns true."""
        zones = {
            "zone1": ZoneState(zone_id="zone1", valve_state=ValveState.OFF),
            "zone2": ZoneState(
                zone_id="zone2",
                valve_state=ValveState.ON,
                open_state_avg=0.90,
                requested_duration=1000.0,
                used_duration=0.0,
            ),
        }
        result = aggregate_heat_request(zones, timing)
        assert result is True

    def test_multiple_zones_requesting(self, timing: TimingParams) -> None:
        """Multiple zones requesting returns true."""
        zones = {
            "zone1": ZoneState(
                zone_id="zone1",
                valve_state=ValveState.ON,
                open_state_avg=0.90,
                requested_duration=1000.0,
            ),
            "zone2": ZoneState(
                zone_id="zone2",
                valve_state=ValveState.ON,
                open_state_avg=0.90,
                requested_duration=1000.0,
            ),
        }
        result = aggregate_heat_request(zones, timing)
        assert result is True


class TestZoneState:
    """Test ZoneState dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        zone = ZoneState(zone_id="test")
        assert zone.zone_id == "test"
        assert zone.circuit_type == CircuitType.REGULAR
        assert zone.current is None
        assert zone.setpoint == 21.0
        assert zone.valve_state == ValveState.UNKNOWN
        assert zone.enabled is True

    def test_flush_circuit_type(self) -> None:
        """Test creating flush circuit zone."""
        zone = ZoneState(zone_id="bathroom", circuit_type=CircuitType.FLUSH)
        assert zone.circuit_type == CircuitType.FLUSH


class TestControllerState:
    """Test ControllerState dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        controller = ControllerState()
        assert controller.mode == "auto"
        assert controller.period_elapsed == 0.0
        assert controller.heat_request is False
        assert controller.flush_enabled is False
        assert controller.dhw_active is False
        assert controller.zones == {}

    def test_with_zones(self) -> None:
        """Test creating controller with zones."""
        zones = {
            "zone1": ZoneState(zone_id="zone1"),
            "zone2": ZoneState(zone_id="zone2"),
        }
        controller = ControllerState(zones=zones)
        assert len(controller.zones) == 2


class TestTimingParams:
    """Test TimingParams dataclass."""

    def test_default_values(self) -> None:
        """Test default values match specification."""
        timing = TimingParams()
        assert timing.observation_period == 7200
        assert timing.min_run_time == 540
        assert timing.valve_open_time == 210
        assert timing.closing_warning_duration == 240
        assert timing.window_block_time == 600

    def test_custom_values(self) -> None:
        """Test custom timing values."""
        timing = TimingParams(
            observation_period=3600,
            min_run_time=300,
        )
        assert timing.observation_period == 3600
        assert timing.min_run_time == 300

    def test_flush_duration_default(self) -> None:
        """Test flush_duration has correct default value."""
        timing = TimingParams()
        assert timing.flush_duration == 480  # 8 minutes


class TestIsFlushRequested:
    """Test cases for is_flush_requested helper function."""

    def test_returns_true_when_dhw_active(self) -> None:
        """Flush is requested when DHW is active."""
        controller = ControllerState(dhw_active=True, flush_until=None)
        assert is_flush_requested(controller) is True

    def test_returns_true_during_post_dhw_period(self) -> None:
        """Flush is requested during post-DHW flush period."""
        future_time = datetime.now(UTC) + timedelta(minutes=5)
        controller = ControllerState(dhw_active=False, flush_until=future_time)
        assert is_flush_requested(controller) is True

    def test_returns_false_when_post_dhw_period_expired(self) -> None:
        """Flush is not requested when post-DHW period has expired."""
        past_time = datetime.now(UTC) - timedelta(minutes=1)
        controller = ControllerState(dhw_active=False, flush_until=past_time)
        assert is_flush_requested(controller) is False

    def test_returns_false_when_no_dhw_and_no_flush_until(self) -> None:
        """Flush is not requested when DHW is off and no flush_until set."""
        controller = ControllerState(dhw_active=False, flush_until=None)
        assert is_flush_requested(controller) is False

    def test_dhw_takes_priority_over_flush_until(self) -> None:
        """DHW active takes priority even if flush_until is expired."""
        past_time = datetime.now(UTC) - timedelta(minutes=1)
        controller = ControllerState(dhw_active=True, flush_until=past_time)
        assert is_flush_requested(controller) is True


class TestEvaluateZoneFlushCircuitPostDHW:
    """Test flush circuit behavior during post-DHW flush period."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create default timing params."""
        return TimingParams()

    def test_flush_during_post_dhw_turns_on(self, timing: TimingParams) -> None:
        """Flush circuit turns on during post-DHW flush period."""
        future_time = datetime.now(UTC) + timedelta(minutes=5)
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=False,  # DHW is off
            flush_until=future_time,  # But in post-DHW flush period
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON

    def test_flush_during_post_dhw_stays_on(self, timing: TimingParams) -> None:
        """Flush circuit stays on during post-DHW flush period."""
        future_time = datetime.now(UTC) + timedelta(minutes=5)
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.ON,
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=False,
            flush_until=future_time,
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_ON

    def test_flush_after_post_dhw_period_expired(self, timing: TimingParams) -> None:
        """Flush circuit follows normal logic after post-DHW period expires."""
        past_time = datetime.now(UTC) - timedelta(minutes=1)
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
            requested_duration=0.0,  # No quota
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=False,
            flush_until=past_time,  # Post-DHW period expired
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        # Should follow normal logic (stays off with no quota)
        assert result == ZoneAction.STAY_OFF

    def test_flush_during_post_dhw_blocked_by_regular_valve_on(
        self, timing: TimingParams
    ) -> None:
        """Flush circuit blocked during post-DHW when regular valve is ON."""
        future_time = datetime.now(UTC) + timedelta(minutes=5)
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
            dhw_active=False,
            flush_until=future_time,
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )
        result = evaluate_zone(flush_zone, controller, timing)
        # Should fall through to normal quota logic (stays off with 0 quota)
        assert result == ZoneAction.STAY_OFF

    def test_flush_during_post_dhw_not_blocked_by_regular_demand_only(
        self, timing: TimingParams
    ) -> None:
        """Flush circuit NOT blocked during post-DHW when regular valve is OFF."""
        future_time = datetime.now(UTC) + timedelta(minutes=5)
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
            valve_state=ValveState.OFF,  # Valve is OFF
            requested_duration=1000.0,  # Has demand but not running
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=False,
            flush_until=future_time,
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )
        result = evaluate_zone(flush_zone, controller, timing)
        # Flush should turn on - regular valve is OFF
        assert result == ZoneAction.TURN_ON


class TestControllerStateFlushUntil:
    """Test ControllerState flush_until field."""

    def test_flush_until_default_none(self) -> None:
        """Test flush_until defaults to None."""
        controller = ControllerState()
        assert controller.flush_until is None

    def test_flush_until_can_be_set(self) -> None:
        """Test flush_until can be set to a datetime."""
        future_time = datetime.now(UTC) + timedelta(minutes=8)
        controller = ControllerState(flush_until=future_time)
        assert controller.flush_until == future_time
