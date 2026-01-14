"""Test zone data structures and helper functions."""

import pytest

from custom_components.ufh_controller.const import TimingParams, ValveState
from custom_components.ufh_controller.core.controller import ControllerState
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
    ZoneState,
    calculate_requested_duration,
    evaluate_zone,
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
