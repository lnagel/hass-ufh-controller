"""Test zone data structures and helper functions."""

import pytest

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    OperationMode,
    TimingConfig,
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
    def timing(self) -> TimingConfig:
        """Create timing config with 7200s period and 540s min run time."""
        return TimingConfig(observation_period=7200, min_run_time=540)

    def test_high_quota_usage_near_period_end_freezes(
        self, timing: TimingConfig
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
        self, timing: TimingConfig
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

    def test_fresh_period_allows_turn_on(self, timing: TimingConfig) -> None:
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
        self, timing: TimingConfig
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


class TestRemainingDuration:
    """Test ZoneState.remaining_duration property."""

    @pytest.mark.parametrize(
        ("enabled", "requested", "used", "expected"),
        [
            (False, 1000.0, 0.0, 0.0),  # disabled
            (True, 0.0, 0.0, 0.0),  # zero quota
            (True, 1000.0, 0.0, 1000.0),  # full quota remaining
            (True, 1000.0, 900.0, 100.0),  # partial quota remaining
            (True, 1000.0, 1000.0, 0.0),  # quota exhausted
            (True, 1000.0, 1100.0, 0.0),  # overused returns zero
        ],
    )
    def test_remaining_duration(
        self,
        enabled: bool,
        requested: float,
        used: float,
        expected: float,
    ) -> None:
        """Test remaining_duration returns correct value for various scenarios."""
        zone = ZoneState(
            zone_id="test",
            enabled=enabled,
            requested_duration=requested,
            used_duration=used,
        )
        assert zone.remaining_duration == expected


class TestControllerState:
    """Test ControllerState dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        controller = ControllerState()
        assert controller.mode == OperationMode.HEAT
        assert controller.period_elapsed == 0.0
        assert controller.heat_request is None
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


class TestTimingConfig:
    """Test TimingConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values match specification."""
        timing = TimingConfig()
        assert timing.observation_period == 7200
        assert timing.min_run_time == 540
        assert timing.valve_open_time == 210
        assert timing.closing_warning_duration == 240
        assert timing.window_block_time == 600

    def test_custom_values(self) -> None:
        """Test custom timing values."""
        timing = TimingConfig(
            observation_period=3600,
            min_run_time=300,
        )
        assert timing.observation_period == 3600
        assert timing.min_run_time == 300

    def test_flush_duration_default(self) -> None:
        """Test flush_duration has correct default value."""
        timing = TimingConfig()
        assert timing.flush_duration == 480  # 8 minutes


class TestZoneRuntimeSupplyCoefficient:
    """Test update_supply_coefficient method."""

    @pytest.fixture
    def zone_runtime(self) -> ZoneRuntime:
        """Create a zone runtime for testing with setpoint=20°C."""
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
        state.setpoint = 20.0  # Explicit setpoint for formula clarity
        return ZoneRuntime(config=config, pid=pid, state=state)

    @pytest.mark.parametrize(
        ("supply_temp", "room_temp", "setpoint", "supply_target", "expected"),
        [
            # Design conditions: (40-20)/(40-20) = 100%
            (40.0, 20.0, 20.0, 40.0, 100.0),
            # Cold room: (40-15)/(40-20) = 125%
            (40.0, 15.0, 20.0, 40.0, 125.0),
            # Very cold room: (40-10)/(40-20) = 150%
            (40.0, 10.0, 20.0, 40.0, 150.0),
            # Room overshooting: (40-22)/(40-20) = 90%
            (40.0, 22.0, 20.0, 40.0, 90.0),
            # Room way above setpoint: (40-25)/(40-20) = 75%
            (40.0, 25.0, 20.0, 40.0, 75.0),
            # Boiler warming up: (30-20)/(40-20) = 50%
            (30.0, 20.0, 20.0, 40.0, 50.0),
            # Hot supply: (45-20)/(40-20) = 125%
            (45.0, 20.0, 20.0, 40.0, 125.0),
            # Different setpoint (22°C): (40-20)/(40-22) ≈ 111.1%
            (40.0, 20.0, 22.0, 40.0, pytest.approx(111.1, rel=0.01)),
        ],
    )
    def test_supply_coefficient_calculation(
        self,
        zone_runtime: ZoneRuntime,
        supply_temp: float,
        room_temp: float,
        setpoint: float,
        supply_target: float,
        expected: float,
    ) -> None:
        """Test supply coefficient formula with various scenarios."""
        zone_runtime.state.current = room_temp
        zone_runtime.state.setpoint = setpoint
        zone_runtime.update_supply_coefficient(
            supply_temp=supply_temp, supply_target_temp=supply_target
        )
        assert zone_runtime.state.supply_coefficient == expected

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

    def test_setpoint_at_supply_target_returns_none(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Setpoint at/above supply target returns None (invalid config)."""
        zone_runtime.state.current = 20.0
        zone_runtime.state.setpoint = 40.0  # Setpoint equals supply target
        zone_runtime.update_supply_coefficient(
            supply_temp=40.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient is None

    def test_setpoint_above_supply_target_returns_none(
        self, zone_runtime: ZoneRuntime
    ) -> None:
        """Setpoint above supply target returns None (invalid config)."""
        zone_runtime.state.current = 20.0
        zone_runtime.state.setpoint = 45.0  # Setpoint above supply target
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
        """Supply coefficient caps at 200% to prevent runaway accumulation."""
        zone_runtime.state.current = 20.0
        # (80-20)/(40-20)*100 = 300%, but should cap at 200%
        zone_runtime.update_supply_coefficient(
            supply_temp=80.0, supply_target_temp=40.0
        )
        assert zone_runtime.state.supply_coefficient == 200.0


class TestUpdateHeatState:
    """Test update_heat_state method."""

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

    @pytest.mark.parametrize(
        ("flow", "supply_coefficient", "expected_heat"),
        [
            # No flow → no heat regardless of supply coefficient
            (False, None, False),
            (False, 50.0, False),
            # Flow + no supply sensor configured → heat follows flow
            (True, None, True),
            # Flow + supply coefficient above threshold (10%) → heat
            (True, 50.0, True),
            # Flow + supply coefficient at threshold boundary → no heat (strict >)
            (True, 10.0, False),
            # Flow + supply coefficient below threshold → no heat
            (True, 5.0, False),
        ],
    )
    def test_heat_state(
        self,
        zone_runtime: ZoneRuntime,
        flow: bool,
        supply_coefficient: float | None,
        expected_heat: bool,
    ) -> None:
        """Test heat state derivation from flow and supply coefficient."""
        zone_runtime.state.flow = flow
        zone_runtime.state.supply_coefficient = supply_coefficient
        zone_runtime.update_heat_state()
        assert zone_runtime.state.heat is expected_heat


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
