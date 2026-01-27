"""Unit tests for ZoneRuntime.update_failure_state timeout selection."""

from datetime import UTC, datetime, timedelta

from custom_components.ufh_controller.const import (
    FAIL_SAFE_TIMEOUT,
    INITIALIZING_TIMEOUT,
    ZoneStatus,
)
from custom_components.ufh_controller.core.pid import PIDController
from custom_components.ufh_controller.core.zone import (
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
    ZoneStatusTransition,
)


def _make_runtime(zone_status: ZoneStatus = ZoneStatus.INITIALIZING) -> ZoneRuntime:
    """Create a ZoneRuntime for testing."""
    config = ZoneConfig(
        zone_id="test_zone",
        name="Test Zone",
        temp_sensor="sensor.test_temp",
        valve_switch="switch.test_valve",
    )
    state = ZoneState(zone_id="test_zone", zone_status=zone_status)
    pid = PIDController(kp=50.0, ki=0.001, kd=0.0)
    return ZoneRuntime(config=config, pid=pid, state=state)


class TestUpdateFailureStateTimeoutSelection:
    """Test that update_failure_state selects the correct timeout."""

    def test_initializing_zone_uses_initializing_timeout(self) -> None:
        """Zone in INITIALIZING uses the shorter initializing_timeout."""
        runtime = _make_runtime(ZoneStatus.INITIALIZING)
        now = datetime.now(UTC)

        # First failure: sets last_successful_update
        runtime.update_failure_state(
            now,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )

        # After initializing_timeout: should trigger fail-safe
        later = now + timedelta(seconds=INITIALIZING_TIMEOUT + 1)
        result = runtime.update_failure_state(
            later,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )

        assert result.transition == ZoneStatusTransition.ENTERED_FAIL_SAFE
        assert result.timeout_used == INITIALIZING_TIMEOUT
        assert runtime.state.zone_status == ZoneStatus.FAIL_SAFE

    def test_initializing_zone_does_not_trigger_before_timeout(self) -> None:
        """Zone in INITIALIZING does NOT trigger fail-safe before timeout."""
        runtime = _make_runtime(ZoneStatus.INITIALIZING)
        now = datetime.now(UTC)

        # First failure: sets last_successful_update
        runtime.update_failure_state(
            now,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )

        # Before initializing_timeout: should NOT trigger fail-safe
        later = now + timedelta(seconds=INITIALIZING_TIMEOUT - 1)
        result = runtime.update_failure_state(
            later,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )

        assert result.transition == ZoneStatusTransition.NONE
        assert result.timeout_used == INITIALIZING_TIMEOUT
        assert runtime.state.zone_status == ZoneStatus.INITIALIZING

    def test_normal_zone_uses_fail_safe_timeout(self) -> None:
        """Zone in NORMAL uses the full fail_safe_timeout."""
        runtime = _make_runtime(ZoneStatus.NORMAL)
        now = datetime.now(UTC)
        runtime.state.last_successful_update = now

        # After initializing_timeout but before fail_safe_timeout
        later = now + timedelta(seconds=INITIALIZING_TIMEOUT + 1)
        result = runtime.update_failure_state(
            later,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )

        # Should NOT be fail-safe - only 120s elapsed, need 3600s
        assert result.transition == ZoneStatusTransition.ENTERED_DEGRADED
        assert result.timeout_used == FAIL_SAFE_TIMEOUT
        assert runtime.state.zone_status == ZoneStatus.DEGRADED

    def test_normal_zone_triggers_fail_safe_after_full_timeout(self) -> None:
        """Zone that was NORMAL transitions directly to FAIL_SAFE after full timeout."""
        runtime = _make_runtime(ZoneStatus.NORMAL)
        now = datetime.now(UTC)
        runtime.state.last_successful_update = now

        # After full fail_safe_timeout: goes directly to FAIL_SAFE
        later = now + timedelta(seconds=FAIL_SAFE_TIMEOUT + 1)
        result = runtime.update_failure_state(
            later,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )
        assert result.transition == ZoneStatusTransition.ENTERED_FAIL_SAFE
        assert result.timeout_used == FAIL_SAFE_TIMEOUT
        assert runtime.state.zone_status == ZoneStatus.FAIL_SAFE

    def test_degraded_zone_uses_fail_safe_timeout(self) -> None:
        """Zone in DEGRADED uses the full fail_safe_timeout."""
        runtime = _make_runtime(ZoneStatus.DEGRADED)
        now = datetime.now(UTC)
        runtime.state.last_successful_update = now

        # After initializing_timeout but before fail_safe_timeout
        later = now + timedelta(seconds=INITIALIZING_TIMEOUT + 1)
        result = runtime.update_failure_state(
            later,
            temp_unavailable=True,
            recorder_failure=False,
            valve_unavailable=False,
        )

        # Should NOT be fail-safe - DEGRADED uses the full timeout
        assert result.transition == ZoneStatusTransition.NONE
        assert result.timeout_used == FAIL_SAFE_TIMEOUT
        assert runtime.state.zone_status == ZoneStatus.DEGRADED
