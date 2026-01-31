"""Test zone data structures and helper functions."""

import pytest

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    OperationMode,
    TimingParams,
    ValveState,
)
from custom_components.ufh_controller.core.controller import ControllerState
from custom_components.ufh_controller.core.pid import PIDController
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
    calculate_requested_duration,
    evaluate_zone,
)


class TestCalculateRequestedDuration:
    """Test cases for calculate_requested_duration."""

    def test_none_duty_cycle(self) -> None:
        """Test None duty cycle returns zero duration."""
        result = calculate_requested_duration(None, 7200)
        assert result == 0.0

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
        assert controller.mode == OperationMode.HEAT
        assert controller.period_elapsed == 0.0
        assert controller.heat_requests == {}
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


class TestZoneRuntimeSupplyCoefficient:
    """Test update_supply_coefficient method."""

    @pytest.fixture
    def zone_runtime(self) -> ZoneRuntime:
        """Create a zone runtime for testing."""
        config = ZoneConfig(
            zone_id="test",
            name="Test Zone",
            temp_sensor="sensor.test",
            valve_switch="switch.test",
            kp=DEFAULT_PID["kp"],
            ki=DEFAULT_PID["ki"],
            kd=DEFAULT_PID["kd"],
        )
        pid = PIDController(
            kp=config.kp,
            ki=config.ki,
            kd=config.kd,
        )
        state = ZoneState(zone_id="test")
        return ZoneRuntime(config=config, pid=pid, state=state)

    def test_supply_at_target_returns_100_percent(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Supply at target temperature gives 100% coefficient."""
        zone_runtime.state.current = 20.0  # Room temp
        zone_runtime.update_supply_coefficient(
            supply_temp=40.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 100.0

    def test_supply_above_target_returns_above_100_percent(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Supply above target gives >100% coefficient."""
        zone_runtime.state.current = 20.0  # Room temp
        # (45-20)/(40-20)*100 = 125%
        zone_runtime.update_supply_coefficient(
            supply_temp=45.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 125.0

    def test_supply_below_target_returns_below_100_percent(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Supply below target gives <100% coefficient."""
        zone_runtime.state.current = 20.0  # Room temp
        # (30-20)/(40-20)*100 = 50%
        zone_runtime.update_supply_coefficient(
            supply_temp=30.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 50.0

    def test_supply_at_room_temp_returns_zero(self, zone_runtime: ZoneRuntime) -> None:
        """Supply at room temp gives 0% coefficient."""
        zone_runtime.state.current = 20.0
        zone_runtime.update_supply_coefficient(
            supply_temp=20.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 0.0

    def test_supply_below_room_temp_returns_zero(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Supply below room temp gives 0% coefficient."""
        zone_runtime.state.current = 20.0
        zone_runtime.update_supply_coefficient(
            supply_temp=15.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 0.0

    def test_room_above_target_returns_none(self, zone_runtime: ZoneRuntime) -> None:
        """Room at/above target returns None (no meaningful ratio)."""
        zone_runtime.state.current = 45.0  # Room above target
        zone_runtime.update_supply_coefficient(
            supply_temp=40.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient is None

    def test_supply_temp_unavailable_returns_none(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """No supply temp returns None."""
        zone_runtime.state.current = 20.0
        zone_runtime.update_supply_coefficient(
            supply_temp=None, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient is None

    def test_room_temp_unavailable_returns_none(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """No room temp returns None."""
        zone_runtime.state.current = None
        zone_runtime.update_supply_coefficient(
            supply_temp=40.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient is None

    def test_caps_at_200_percent(self, zone_runtime: ZoneRuntime) -> None:
        """Supply coefficient caps at 200%."""
        zone_runtime.state.current = 20.0
        # (80-20)/(40-20)*100 = 300%, but should cap at 200%
        zone_runtime.update_supply_coefficient(
            supply_temp=80.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 200.0


class TestZoneRuntimeUsedDuration:
    """Test update_used_duration method."""

    @pytest.fixture
    def zone_runtime(self) -> ZoneRuntime:
        """Create a zone runtime for testing."""
        config = ZoneConfig(
            zone_id="test",
            name="Test Zone",
            temp_sensor="sensor.test",
            valve_switch="switch.test",
        )
        pid = PIDController(kp=50.0, ki=0.0, kd=0.0)
        state = ZoneState(zone_id="test")
        return ZoneRuntime(config=config, pid=pid, state=state)

    def test_flow_true_no_coefficient_increments_by_dt(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Flow=True without supply_coefficient increments by dt (fallback)."""
        zone_runtime.state.flow = True
        zone_runtime.state.supply_coefficient = None
        zone_runtime.state.used_duration = 100.0

        zone_runtime.update_used_duration(60.0)

        assert zone_runtime.state.used_duration == 160.0

    def test_flow_false_does_not_accumulate(self, zone_runtime: ZoneRuntime) -> None:
        """Flow=False means no accumulation."""
        zone_runtime.state.flow = False
        zone_runtime.state.supply_coefficient = 100.0
        zone_runtime.state.used_duration = 100.0

        zone_runtime.update_used_duration(60.0)

        assert zone_runtime.state.used_duration == 100.0  # Unchanged

    def test_flow_true_with_100_percent_coefficient(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Flow=True with 100% coefficient increments by dt."""
        zone_runtime.state.flow = True
        zone_runtime.state.supply_coefficient = 100.0
        zone_runtime.state.used_duration = 100.0

        zone_runtime.update_used_duration(60.0)

        assert zone_runtime.state.used_duration == 160.0

    def test_flow_true_with_120_percent_coefficient(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Flow=True with 120% coefficient increments by 1.2 * dt."""
        zone_runtime.state.flow = True
        zone_runtime.state.supply_coefficient = 120.0
        zone_runtime.state.used_duration = 100.0

        zone_runtime.update_used_duration(60.0)

        # 100 + 60 * 1.2 = 172
        assert zone_runtime.state.used_duration == 172.0

    def test_flow_true_with_50_percent_coefficient(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Flow=True with 50% coefficient increments by 0.5 * dt."""
        zone_runtime.state.flow = True
        zone_runtime.state.supply_coefficient = 50.0
        zone_runtime.state.used_duration = 100.0

        zone_runtime.update_used_duration(60.0)

        # 100 + 60 * 0.5 = 130
        assert zone_runtime.state.used_duration == 130.0

    def test_reset_used_duration(self, zone_runtime: ZoneRuntime) -> None:
        """Reset clears used_duration to zero."""
        zone_runtime.state.used_duration = 5000.0
        zone_runtime.reset_used_duration()
        assert zone_runtime.state.used_duration == 0.0


class TestZoneRuntimeRequestedDuration:
    """Test update_requested_duration method."""

    @pytest.fixture
    def zone_runtime(self) -> ZoneRuntime:
        """Create a zone runtime for testing."""
        config = ZoneConfig(
            zone_id="test",
            name="Test Zone",
            temp_sensor="sensor.test",
            valve_switch="switch.test",
        )
        pid = PIDController(kp=50.0, ki=0.0, kd=0.0)
        state = ZoneState(zone_id="test")
        return ZoneRuntime(config=config, pid=pid, state=state)

    def test_updates_from_duty_cycle(self, zone_runtime: ZoneRuntime) -> None:
        """Requested duration calculated from current duty cycle."""
        # Set up a duty cycle via PID update
        zone_runtime.state.current = 19.0  # 2 degrees below setpoint
        zone_runtime.update_pid(60.0, OperationMode.HEAT)

        zone_runtime.update_requested_duration(7200)

        # With 2 degree error and Kp=50, duty_cycle = 100% (clamped)
        assert zone_runtime.state.requested_duration == 7200.0

    def test_no_pid_state_returns_zero(self, zone_runtime: ZoneRuntime) -> None:
        """No PID state means zero requested duration."""
        # Don't call update_pid - state is None
        zone_runtime.update_requested_duration(7200)
        assert zone_runtime.state.requested_duration == 0.0
