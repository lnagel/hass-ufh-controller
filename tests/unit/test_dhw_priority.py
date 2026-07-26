"""Test DHW priority levels and the absolute-priority block."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ufh_controller.const import (
    DEFAULT_DHW_PRIORITY,
    FAIL_SAFE_TIMEOUT,
    ControllerStatus,
    DHWPriority,
    OperationMode,
    TimingConfig,
    ValveState,
    ZoneStatus,
)
from custom_components.ufh_controller.coordinator import _parse_dhw_priority
from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    ControllerState,
    HeatingController,
    is_dhw_sensor_faulted,
)
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
    ZoneConfig,
    ZoneState,
    evaluate_zone,
)
from tests.conftest import setup_zone_historical, setup_zone_pid

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
RECOVERY = 300
FLUSH_DURATION = 480


def make_config(
    priority: DHWPriority,
    *,
    recovery: int = RECOVERY,
    flush_duration: int = FLUSH_DURATION,
) -> ControllerConfig:
    """Build a two-zone controller config with the given DHW priority."""
    return ControllerConfig(
        controller_id="heating",
        name="Heating Controller",
        dhw_active_entity="binary_sensor.boiler_dhw",
        dhw_priority=priority,
        timing=TimingConfig(
            dhw_recovery_time=recovery,
            flush_duration=flush_duration,
        ),
        zones=[
            ZoneConfig(
                zone_id="living_room",
                name="Living Room",
                temp_sensor="sensor.living_room_temp",
                valve_switch="switch.living_room_valve",
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


class TestEvaluateZoneDHWBlock:
    """The block closes every circuit and overrides every other path."""

    @pytest.fixture
    def timing(self) -> TimingConfig:
        """Create default timing config."""
        return TimingConfig()

    @pytest.fixture
    def blocked(self) -> ControllerState:
        """Create controller state with the DHW block asserted."""
        return ControllerState(started_at=NOW, dhw_block=True, dhw_active=True)

    def test_running_zone_turns_off(
        self, timing: TimingConfig, blocked: ControllerState
    ) -> None:
        """A zone already ON is closed, overriding the STAY_ON path."""
        zone = ZoneState(
            zone_id="living_room",
            valve_state=ValveState.ON,
            requested_duration=3600.0,
            used_duration=0.0,
        )
        assert evaluate_zone(zone, blocked, timing) == ZoneAction.TURN_OFF

    def test_closed_zone_stays_off(
        self, timing: TimingConfig, blocked: ControllerState
    ) -> None:
        """A zone already OFF stays off without a redundant command."""
        zone = ZoneState(
            zone_id="living_room",
            valve_state=ValveState.OFF,
            requested_duration=3600.0,
        )
        assert evaluate_zone(zone, blocked, timing) == ZoneAction.STAY_OFF

    @pytest.mark.parametrize(
        "valve_state", [ValveState.UNKNOWN, ValveState.UNAVAILABLE]
    )
    def test_uncertain_valve_turns_off(
        self,
        timing: TimingConfig,
        blocked: ControllerState,
        valve_state: ValveState,
    ) -> None:
        """An uncertain valve state is actively driven closed."""
        zone = ZoneState(zone_id="living_room", valve_state=valve_state)
        assert evaluate_zone(zone, blocked, timing) == ZoneAction.TURN_OFF

    def test_overrides_end_of_period_freeze(self, timing: TimingConfig) -> None:
        """The block wins over the end-of-observation-period valve freeze."""
        blocked = ControllerState(
            started_at=NOW,
            dhw_block=True,
            dhw_active=True,
            period_elapsed=timing.observation_period - 60,
        )
        zone = ZoneState(zone_id="living_room", valve_state=ValveState.ON)
        assert evaluate_zone(zone, blocked, timing) == ZoneAction.TURN_OFF

    def test_flush_circuit_under_quota_scheduling_is_blocked(
        self, timing: TimingConfig
    ) -> None:
        """
        A flush circuit with capture disabled is closed too.

        The soft gate only ever covered regular circuits; the hazard the block
        guards against is hydraulic, so it applies to every circuit type.
        """
        blocked = ControllerState(
            started_at=NOW,
            dhw_block=True,
            dhw_active=True,
            flush_enabled=False,
        )
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.ON,
            requested_duration=3600.0,
        )
        assert evaluate_zone(zone, blocked, timing) == ZoneAction.TURN_OFF

    def test_flush_activation_is_blocked(self, timing: TimingConfig) -> None:
        """Even an explicit flush_request cannot open a circuit while blocked."""
        blocked = ControllerState(
            started_at=NOW,
            dhw_block=True,
            flush_enabled=True,
        )
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        result = evaluate_zone(zone, blocked, timing, flush_request=True)
        assert result == ZoneAction.STAY_OFF

    def test_disabled_zone_still_short_circuits_first(
        self, timing: TimingConfig, blocked: ControllerState
    ) -> None:
        """A disabled zone is closed regardless of the block."""
        zone = ZoneState(
            zone_id="living_room", enabled=False, valve_state=ValveState.ON
        )
        assert evaluate_zone(zone, blocked, timing) == ZoneAction.TURN_OFF


class TestUpdateDHWStateTimers:
    """Timer arithmetic across the DHW edges for each priority."""

    def test_absolute_arms_hold_off_on_dhw_end(self) -> None:
        """Block persists through the recovery window after DHW ends."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=True, now=NOW)
        assert controller.state.dhw_block is True

        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)
        assert controller.state.dhw_block is True
        assert controller.state.dhw_block_until == end + timedelta(seconds=RECOVERY)

        controller.update_dhw_state(
            dhw_active=False, now=end + timedelta(seconds=RECOVERY - 1)
        )
        assert controller.state.dhw_block is True

        controller.update_dhw_state(
            dhw_active=False, now=end + timedelta(seconds=RECOVERY + 1)
        )
        assert controller.state.dhw_block is False

    def test_absolute_defers_flush_window_past_hold_off(self) -> None:
        """The flush window is delayed by the recovery time, not shortened."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        assert controller.state.flush_until == end + timedelta(
            seconds=RECOVERY + FLUSH_DURATION
        )

    @pytest.mark.parametrize("priority", [DHWPriority.PARTIAL, DHWPriority.PARALLEL])
    def test_non_absolute_leaves_flush_window_unchanged(
        self, priority: DHWPriority
    ) -> None:
        """Partial and parallel keep the historical flush timing exactly."""
        controller = HeatingController(make_config(priority), started_at=NOW)
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        assert controller.state.flush_until == end + timedelta(seconds=FLUSH_DURATION)
        assert controller.state.dhw_block is False

    def test_hold_off_armed_even_with_capture_disabled(self) -> None:
        """The safety timer does not depend on the flush feature being on."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        assert controller.state.flush_enabled is False

        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        assert controller.state.dhw_block_until == end + timedelta(seconds=RECOVERY)
        assert controller.state.dhw_block is True
        assert controller.state.flush_until is None

    def test_zero_recovery_clears_block_immediately(self) -> None:
        """Recovery of zero means the block covers DHW only."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE, recovery=0), started_at=NOW
        )
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        assert controller.state.dhw_block is False
        assert controller.state.flush_until == end + timedelta(seconds=FLUSH_DURATION)

    def test_dhw_reasserts_during_recovery(self) -> None:
        """A new DHW cycle clears the flush timer and re-blocks."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.state.flush_enabled = True

        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        restart = end + timedelta(seconds=60)
        controller.update_dhw_state(dhw_active=True, now=restart)
        assert controller.state.flush_until is None
        assert controller.state.dhw_block is True

        second_end = restart + timedelta(minutes=5)
        controller.update_dhw_state(dhw_active=False, now=second_end)
        assert controller.state.dhw_block_until == second_end + timedelta(
            seconds=RECOVERY
        )
        assert controller.state.flush_until == second_end + timedelta(
            seconds=RECOVERY + FLUSH_DURATION
        )

    def test_block_clears_when_priority_lowered(self) -> None:
        """Dropping out of absolute releases an in-progress block."""
        config = make_config(DHWPriority.ABSOLUTE)
        controller = HeatingController(config, started_at=NOW)

        controller.update_dhw_state(dhw_active=True, now=NOW)
        assert controller.state.dhw_block is True

        config.dhw_priority = DHWPriority.PARTIAL
        controller.update_dhw_state(dhw_active=True, now=NOW + timedelta(seconds=60))
        assert controller.state.dhw_block is False


class TestDHWBlockModeInteraction:
    """Mode dispatch while the block is asserted."""

    @pytest.mark.parametrize(
        "mode", [OperationMode.FLUSH, OperationMode.CYCLE, OperationMode.HEAT]
    )
    def test_automatic_modes_close_all_valves(self, mode: OperationMode) -> None:
        """Heat, flush and cycle all yield closed valves and no requests."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.mode = mode

        # A zone still reporting flow, so the pump assertion is load-bearing
        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_historical(
            controller, "living_room", valve_position=1.0, window=False
        )
        controller.get_zone_runtime("living_room").update_requested_duration(7200)
        controller.get_zone_runtime("living_room").state.valve_state = ValveState.ON

        controller.update_dhw_state(dhw_active=True, now=NOW)

        actions = controller.evaluate(now=NOW)

        assert all(
            action in {ZoneAction.TURN_OFF, ZoneAction.STAY_OFF}
            for action in actions.valve_actions.values()
        )
        assert actions.heat_request is False
        assert not actions.pump_request

    def test_flush_mode_resumes_after_block_clears(self) -> None:
        """The mode is suspended, not cancelled."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.mode = OperationMode.FLUSH
        controller.update_dhw_state(dhw_active=True, now=NOW)
        assert controller.mode == OperationMode.FLUSH

        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)
        after = end + timedelta(seconds=RECOVERY + 1)
        controller.update_dhw_state(dhw_active=False, now=after)

        actions = controller.evaluate(now=after)
        assert all(
            action in {ZoneAction.TURN_ON, ZoneAction.STAY_ON}
            for action in actions.valve_actions.values()
        )
        assert actions.pump_request is True

    def test_all_on_is_not_overridden(self) -> None:
        """Explicit manual override states user intent and is respected."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.mode = OperationMode.ALL_ON
        controller.update_dhw_state(dhw_active=True, now=NOW)

        actions = controller.evaluate(now=NOW)
        assert all(
            action in {ZoneAction.TURN_ON, ZoneAction.STAY_ON}
            for action in actions.valve_actions.values()
        )

    def test_block_and_flush_request_are_mutually_exclusive(self) -> None:
        """The invariant that makes evaluate_zone ordering non-load-bearing."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.state.flush_enabled = True
        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        step = timedelta(seconds=30)
        moment = NOW
        saw_flush_request = False
        while moment <= end + timedelta(seconds=RECOVERY + FLUSH_DURATION + 60):
            controller.update_dhw_state(dhw_active=NOW <= moment < end, now=moment)
            actions = controller.evaluate(now=moment)
            assert not (controller.state.dhw_block and actions.flush_request)
            saw_flush_request |= actions.flush_request
            moment += step

        # The flush window must actually open, or the invariant is vacuous
        assert saw_flush_request is True


class TestDHWPriorityBackwardCompatibility:
    """Partial priority must reproduce the historical soft gate exactly."""

    def test_partial_keeps_running_zone_on(self) -> None:
        """A zone already ON continues through DHW under partial priority."""
        controller = HeatingController(make_config(DHWPriority.PARTIAL), started_at=NOW)
        controller.update_dhw_state(dhw_active=True, now=NOW)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_historical(
            controller, "living_room", valve_position=1.0, window=False
        )
        runtime = controller.get_zone_runtime("living_room")
        runtime.update_requested_duration(7200)
        runtime.state.valve_state = ValveState.ON

        actions = controller.evaluate(now=NOW)
        assert actions.valve_actions["living_room"] == ZoneAction.STAY_ON

    def test_partial_blocks_new_start(self) -> None:
        """A zone that is OFF cannot start under partial priority."""
        controller = HeatingController(make_config(DHWPriority.PARTIAL), started_at=NOW)
        controller.update_dhw_state(dhw_active=True, now=NOW)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_historical(
            controller, "living_room", valve_position=0.0, window=False
        )
        runtime = controller.get_zone_runtime("living_room")
        runtime.update_requested_duration(7200)
        runtime.state.valve_state = ValveState.OFF

        actions = controller.evaluate(now=NOW)
        assert actions.valve_actions["living_room"] == ZoneAction.STAY_OFF

    def test_parallel_allows_new_start_during_dhw(self) -> None:
        """Parallel priority ignores DHW entirely."""
        controller = HeatingController(
            make_config(DHWPriority.PARALLEL), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=True, now=NOW)

        setup_zone_pid(controller, "living_room", 20.0, 60.0)
        setup_zone_historical(
            controller, "living_room", valve_position=0.0, window=False
        )
        runtime = controller.get_zone_runtime("living_room")
        runtime.update_requested_duration(7200)
        runtime.state.valve_state = ValveState.OFF

        actions = controller.evaluate(now=NOW)
        assert actions.valve_actions["living_room"] == ZoneAction.TURN_ON


class TestIsDHWSensorFaulted:
    """An unreadable DHW sensor is a fault only under absolute priority."""

    @pytest.mark.parametrize(
        ("priority", "expected"),
        [
            (DHWPriority.ABSOLUTE, True),
            (DHWPriority.PARTIAL, False),
            (DHWPriority.PARALLEL, False),
        ],
    )
    def test_unavailable_sensor(self, priority: DHWPriority, expected: bool) -> None:
        """Only absolute treats an unreadable sensor as a fault."""
        assert (
            is_dhw_sensor_faulted(sensor_available=False, priority=priority) is expected
        )

    @pytest.mark.parametrize("priority", list(DHWPriority))
    def test_available_sensor_is_never_a_fault(self, priority: DHWPriority) -> None:
        """A usable reading is never a fault, whatever the priority."""
        assert is_dhw_sensor_faulted(sensor_available=True, priority=priority) is False


class TestDHWSensorLoss:
    """An unreadable DHW sensor faults and blocks, rather than being inferred."""

    def test_fault_blocks_and_freezes_timers(self) -> None:
        """No edge detection while unreadable, so no timer is armed."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=True, now=NOW)
        assert controller.state.dhw_block is True

        for step in range(1, 12):
            moment = NOW + timedelta(seconds=60 * step)
            controller.update_dhw_state(
                dhw_active=False, now=moment, sensor_available=False
            )

        # Well past the hold-off duration, but no edge was ever detected
        assert controller.state.dhw_sensor_fault is True
        assert controller.state.dhw_sensor_fault_since == NOW + timedelta(seconds=60)
        assert controller.state.dhw_block is True
        assert controller.state.dhw_block_until is None
        assert controller.state.flush_until is None
        assert controller.state.dhw_sensor_available is False

    def test_fault_blocks_even_when_last_known_was_off(self) -> None:
        """The block does not depend on what the sensor last said."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=False, now=NOW)
        assert controller.state.dhw_block is False

        controller.update_dhw_state(
            dhw_active=False,
            now=NOW + timedelta(seconds=60),
            sensor_available=False,
        )
        assert controller.state.dhw_block is True

    def test_fault_raises_controller_status_to_degraded(self) -> None:
        """A live fault is surfaced through the controller status."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=False, now=NOW, sensor_available=False)
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    @pytest.mark.parametrize("priority", [DHWPriority.PARTIAL, DHWPriority.PARALLEL])
    def test_non_absolute_priorities_do_not_fault(self, priority: DHWPriority) -> None:
        """Historical fail-open behaviour is unchanged where damage is not at stake."""
        controller = HeatingController(make_config(priority), started_at=NOW)
        controller.update_dhw_state(dhw_active=False, now=NOW, sensor_available=False)
        controller.update_status(now=NOW, has_pending_entities=False)

        assert controller.state.dhw_sensor_fault is False
        assert controller.state.dhw_block is False
        assert controller.status != ControllerStatus.DEGRADED

    def test_recovery_is_timed_from_when_the_sensor_returns(self) -> None:
        """The hold-off starts when visibility is regained, not at the dropout."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=True, now=NOW)

        outage = NOW + timedelta(minutes=5)
        controller.update_dhw_state(
            dhw_active=False, now=outage, sensor_available=False
        )
        assert controller.state.dhw_block_until is None

        returned = NOW + timedelta(minutes=10)
        controller.update_dhw_state(
            dhw_active=False, now=returned, sensor_available=True
        )
        assert controller.state.dhw_sensor_fault is False
        assert controller.state.dhw_block_until == returned + timedelta(
            seconds=RECOVERY
        )

        after = returned + timedelta(seconds=RECOVERY + 1)
        controller.update_dhw_state(dhw_active=False, now=after)
        assert controller.state.dhw_block is False
        assert controller.state.dhw_sensor_available is True


class TestParseDHWPriority:
    """Stored priority values are parsed defensively."""

    @pytest.mark.parametrize("priority", list(DHWPriority))
    def test_known_values_round_trip(self, priority: DHWPriority) -> None:
        """Every enum member parses back to itself."""
        assert _parse_dhw_priority(priority.value) is priority

    @pytest.mark.parametrize("value", [None, "", "Absolute", "aggressive", 42])
    def test_unusable_values_fall_back(self, value: object) -> None:
        """Missing or unrecognised values degrade instead of failing setup."""
        assert _parse_dhw_priority(value) is DEFAULT_DHW_PRIORITY


class TestHoldOffDeadlineCleanup:
    """The recovery deadline does not linger once it has passed."""

    def test_expired_deadline_is_cleared(self) -> None:
        """A passed deadline stops being reported as pending."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)
        assert controller.state.dhw_block_until is not None

        controller.update_dhw_state(
            dhw_active=False, now=end + timedelta(seconds=RECOVERY + 1)
        )
        assert controller.state.dhw_block is False
        assert controller.state.dhw_block_until is None

    def test_pending_deadline_is_retained(self) -> None:
        """A deadline still in the future is left alone."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        controller.update_dhw_state(
            dhw_active=False, now=end + timedelta(seconds=RECOVERY - 1)
        )
        assert controller.state.dhw_block is True
        assert controller.state.dhw_block_until == end + timedelta(seconds=RECOVERY)


class TestDHWFaultEscalation:
    """A sustained DHW sensor fault escalates to controller fail-safe."""

    def _faulted(self, at: datetime) -> HeatingController:
        """Create a controller with a live DHW sensor fault."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=False, now=at, sensor_available=False)
        return controller

    def test_stays_degraded_before_the_timeout(self) -> None:
        """Escalation waits, matching how zone failures escalate."""
        controller = self._faulted(NOW)
        later = NOW + timedelta(seconds=FAIL_SAFE_TIMEOUT - 60)
        controller.update_dhw_state(dhw_active=False, now=later, sensor_available=False)
        controller.update_status(now=later, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_escalates_after_the_timeout(self) -> None:
        """A persistent fault reaches fail-safe so the boiler is handed back."""
        controller = self._faulted(NOW)
        later = NOW + timedelta(seconds=FAIL_SAFE_TIMEOUT + 60)
        controller.update_dhw_state(dhw_active=False, now=later, sensor_available=False)
        controller.update_status(now=later, has_pending_entities=False)
        assert controller.status == ControllerStatus.FAIL_SAFE

    def test_recovery_before_the_timeout_never_escalates(self) -> None:
        """A transient dropout resets the clock rather than accumulating."""
        controller = self._faulted(NOW)

        back = NOW + timedelta(seconds=60)
        controller.update_dhw_state(dhw_active=False, now=back, sensor_available=True)
        assert controller.state.dhw_sensor_fault is False
        assert controller.state.dhw_sensor_fault_since is None

        # A later fault starts a fresh clock, not one carried over
        again = back + timedelta(seconds=60)
        controller.update_dhw_state(dhw_active=False, now=again, sensor_available=False)
        assert controller.state.dhw_sensor_fault_since == again

        soon = again + timedelta(seconds=FAIL_SAFE_TIMEOUT - 60)
        controller.update_dhw_state(dhw_active=False, now=soon, sensor_available=False)
        controller.update_status(now=soon, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_pending_fault_never_downgrades_zone_fail_safe(self) -> None:
        """
        A DHW fault only ever raises the status, so it must not lower one.

        Both escalation paths write the same field, and zone aggregation can
        reach fail-safe while the DHW clock is still running. Reporting
        DEGRADED there would call the controller healthier than its zones are.
        """
        controller = self._faulted(NOW)
        for runtime in controller.zone_runtimes:
            runtime.state.zone_status = ZoneStatus.FAIL_SAFE

        soon = NOW + timedelta(seconds=60)
        controller.update_dhw_state(dhw_active=False, now=soon, sensor_available=False)
        controller.update_status(now=soon, has_pending_entities=False)

        assert controller.status == ControllerStatus.FAIL_SAFE
        assert controller.fail_safe_reason == "dhw_sensor_unavailable"


class TestHoldOffScoping:
    """The hold-off deadline exists only where a block can engage."""

    @pytest.mark.parametrize("priority", [DHWPriority.PARTIAL, DHWPriority.PARALLEL])
    def test_no_deadline_armed_without_absolute(self, priority: DHWPriority) -> None:
        """
        Non-absolute priorities never arm the hold-off.

        Arming it regardless meant partial and parallel users saw a populated
        "Block Until" attribute, and had it persisted, for a block that could
        never engage.
        """
        controller = HeatingController(make_config(priority), started_at=NOW)
        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        assert controller.state.dhw_block_until is None
        assert controller.state.dhw_block is False

    def test_deadline_armed_under_absolute(self) -> None:
        """Absolute still arms it, so the block has something to run on."""
        controller = HeatingController(
            make_config(DHWPriority.ABSOLUTE), started_at=NOW
        )
        controller.update_dhw_state(dhw_active=True, now=NOW)
        end = NOW + timedelta(minutes=10)
        controller.update_dhw_state(dhw_active=False, now=end)

        assert controller.state.dhw_block_until == end + timedelta(seconds=RECOVERY)
