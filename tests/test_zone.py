"""Test zone state and decision logic."""

import pytest

from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ControllerState,
    TimingParams,
    ZoneAction,
    ZoneState,
    aggregate_heat_request,
    calculate_requested_duration,
    evaluate_zone,
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
        zone = ZoneState(zone_id="test", enabled=False, valve_on=False)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_disabled_zone_valve_on(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Disabled zone with valve on turns off."""
        zone = ZoneState(zone_id="test", enabled=False, valve_on=True)
        result = evaluate_zone(zone, controller, timing)
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
            valve_on=False,
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
            valve_on=True,
        )
        controller = ControllerState(
            flush_enabled=True,
            dhw_active=True,
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_ON

    def test_flush_blocked_by_regular_demand(self, timing: TimingParams) -> None:
        """Flush circuit blocked when regular circuit has demand."""
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_on=False,
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
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

    def test_flush_disabled_no_priority(self, timing: TimingParams) -> None:
        """Flush circuit follows normal logic when flush disabled."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_on=False,
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
    """Test window blocking behavior."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params with 5% threshold."""
        return TimingParams(window_block_threshold=0.05)

    @pytest.fixture
    def controller(self) -> ControllerState:
        """Create default controller state."""
        return ControllerState()

    def test_window_blocked_valve_off(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Window open stays off."""
        zone = ZoneState(
            zone_id="test",
            valve_on=False,
            window_open_avg=0.10,  # Above 5% threshold
            requested_duration=1000.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF

    def test_window_blocked_valve_on(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Window open turns off valve."""
        zone = ZoneState(
            zone_id="test",
            valve_on=True,
            window_open_avg=0.10,  # Above 5% threshold
            requested_duration=1000.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_OFF

    def test_window_below_threshold(
        self, timing: TimingParams, controller: ControllerState
    ) -> None:
        """Window average below threshold doesn't block."""
        zone = ZoneState(
            zone_id="test",
            valve_on=False,
            window_open_avg=0.03,  # Below 5% threshold
            requested_duration=1000.0,
            used_duration=0.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON


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
            valve_on=False,
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
            valve_on=True,
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
            valve_on=False,
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
            valve_on=True,
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
            valve_on=False,
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
            valve_on=False,
            requested_duration=0.0,
            used_duration=0.0,
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_OFF


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
            valve_on=False,
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
            valve_on=False,
            requested_duration=1000.0,
            used_duration=0.0,
        )
        controller = ControllerState(dhw_active=False)
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON


class TestShouldRequestHeat:
    """Test cases for should_request_heat."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create timing params."""
        return TimingParams(closing_warning_duration=240)

    def test_valve_off_no_request(self, timing: TimingParams) -> None:
        """Valve off doesn't request heat."""
        zone = ZoneState(zone_id="test", valve_on=False)
        result = should_request_heat(zone, timing)
        assert result is False

    def test_disabled_zone_no_request(self, timing: TimingParams) -> None:
        """Disabled zone doesn't request heat."""
        zone = ZoneState(
            zone_id="test",
            valve_on=True,
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
            valve_on=True,
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
            valve_on=True,
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
            valve_on=True,
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
            "zone1": ZoneState(zone_id="zone1", valve_on=False),
            "zone2": ZoneState(zone_id="zone2", valve_on=False),
        }
        result = aggregate_heat_request(zones, timing)
        assert result is False

    def test_one_zone_requesting(self, timing: TimingParams) -> None:
        """One zone requesting returns true."""
        zones = {
            "zone1": ZoneState(zone_id="zone1", valve_on=False),
            "zone2": ZoneState(
                zone_id="zone2",
                valve_on=True,
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
                valve_on=True,
                open_state_avg=0.90,
                requested_duration=1000.0,
            ),
            "zone2": ZoneState(
                zone_id="zone2",
                valve_on=True,
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
        assert zone.duty_cycle == 0.0
        assert zone.valve_on is False
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
        assert timing.duty_cycle_window == 3600
        assert timing.min_run_time == 540
        assert timing.valve_open_time == 210
        assert timing.closing_warning_duration == 240
        assert timing.window_block_threshold == 0.05

    def test_custom_values(self) -> None:
        """Test custom timing values."""
        timing = TimingParams(
            observation_period=3600,
            min_run_time=300,
        )
        assert timing.observation_period == 3600
        assert timing.min_run_time == 300
