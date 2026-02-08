"""Tests for HeatingController.update_status() and status property."""

from datetime import UTC, datetime, timedelta

from custom_components.ufh_controller.const import (
    INITIALIZING_TIMEOUT,
    ControllerStatus,
    ZoneStatus,
)
from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    HeatingController,
    ZoneConfig,
)

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)


def _make_controller(zone_count: int = 2) -> HeatingController:
    """Create a controller with the given number of zones."""
    zones = [
        ZoneConfig(
            zone_id=f"zone{i}",
            name=f"Zone {i}",
            temp_sensor=f"sensor.zone{i}_temp",
            valve_switch=f"switch.zone{i}_valve",
        )
        for i in range(1, zone_count + 1)
    ]
    config = ControllerConfig(
        controller_id="heating",
        name="Heating Controller",
        zones=zones,
    )
    return HeatingController(config, started_at=NOW)


class TestStatusProperty:
    """Test status property delegates to state."""

    def test_status_returns_state_status(self) -> None:
        """Test status property returns current state.status."""
        controller = _make_controller()
        assert controller.status == ControllerStatus.INITIALIZING

        controller.state.status = ControllerStatus.NORMAL
        assert controller.status == ControllerStatus.NORMAL


class TestZoneAggregation:
    """Test zone status aggregation in update_status."""

    def test_no_zones_returns_normal(self) -> None:
        """Test controller with no zones goes to NORMAL."""
        controller = _make_controller(zone_count=0)
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.NORMAL

    def test_all_initializing(self) -> None:
        """Test all zones INITIALIZING → controller INITIALIZING."""
        controller = _make_controller()
        # Zones start as INITIALIZING by default
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.INITIALIZING

    def test_all_normal(self) -> None:
        """Test all zones NORMAL → controller NORMAL."""
        controller = _make_controller()
        for rt in controller.zone_runtimes:
            rt.state.zone_status = ZoneStatus.NORMAL
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.NORMAL

    def test_mix_normal_and_degraded(self) -> None:
        """Test mix of NORMAL + DEGRADED → controller DEGRADED."""
        controller = _make_controller()
        controller.zone_runtimes[0].state.zone_status = ZoneStatus.NORMAL
        controller.zone_runtimes[1].state.zone_status = ZoneStatus.DEGRADED
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_mix_normal_and_fail_safe(self) -> None:
        """Test mix of NORMAL + FAIL_SAFE → controller DEGRADED."""
        controller = _make_controller()
        controller.zone_runtimes[0].state.zone_status = ZoneStatus.NORMAL
        controller.zone_runtimes[1].state.zone_status = ZoneStatus.FAIL_SAFE
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_all_fail_safe(self) -> None:
        """Test all zones FAIL_SAFE → controller FAIL_SAFE."""
        controller = _make_controller()
        for rt in controller.zone_runtimes:
            rt.state.zone_status = ZoneStatus.FAIL_SAFE
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.FAIL_SAFE

    def test_mix_initializing_and_fail_safe(self) -> None:
        """Test mix of INITIALIZING + FAIL_SAFE → controller DEGRADED."""
        controller = _make_controller()
        controller.zone_runtimes[0].state.zone_status = ZoneStatus.INITIALIZING
        controller.zone_runtimes[1].state.zone_status = ZoneStatus.FAIL_SAFE
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_mix_initializing_and_degraded(self) -> None:
        """Test mix of INITIALIZING + DEGRADED → controller DEGRADED."""
        controller = _make_controller()
        controller.zone_runtimes[0].state.zone_status = ZoneStatus.INITIALIZING
        controller.zone_runtimes[1].state.zone_status = ZoneStatus.DEGRADED
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_mix_degraded_and_fail_safe(self) -> None:
        """Test mix of DEGRADED + FAIL_SAFE → controller DEGRADED."""
        controller = _make_controller()
        controller.zone_runtimes[0].state.zone_status = ZoneStatus.DEGRADED
        controller.zone_runtimes[1].state.zone_status = ZoneStatus.FAIL_SAFE
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_controller_never_fail_safe_if_one_zone_works(self) -> None:
        """Test controller never enters fail-safe if at least one zone is working."""
        controller = _make_controller()
        controller.zone_runtimes[0].state.zone_status = ZoneStatus.NORMAL
        controller.zone_runtimes[1].state.zone_status = ZoneStatus.FAIL_SAFE
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.DEGRADED

    def test_controller_fail_safe_only_when_all_zones_fail(self) -> None:
        """Test controller fail-safe requires all zones in fail-safe."""
        controller = _make_controller()
        for rt in controller.zone_runtimes:
            rt.state.zone_status = ZoneStatus.FAIL_SAFE
        controller.update_status(now=NOW, has_pending_entities=False)
        assert controller.status == ControllerStatus.FAIL_SAFE


class TestInitTimeout:
    """Test initialization timeout in update_status."""

    def test_pending_within_timeout_stays_initializing(self) -> None:
        """Test pending entities within timeout → stays INITIALIZING."""
        controller = _make_controller()
        # Just after init, well within timeout
        controller.update_status(
            now=NOW + timedelta(seconds=10), has_pending_entities=True
        )
        assert controller.status == ControllerStatus.INITIALIZING

    def test_pending_after_timeout_transitions(self) -> None:
        """Test pending entities after timeout → transitions based on zones."""
        controller = _make_controller()
        # All zones NORMAL so we can observe the transition
        for rt in controller.zone_runtimes:
            rt.state.zone_status = ZoneStatus.NORMAL

        controller.update_status(
            now=NOW + timedelta(seconds=INITIALIZING_TIMEOUT + 1),
            has_pending_entities=True,
        )
        assert controller.status == ControllerStatus.NORMAL

    def test_no_pending_ignores_timeout(self) -> None:
        """Test no pending entities → ignores timeout, transitions based on zones."""
        controller = _make_controller()
        for rt in controller.zone_runtimes:
            rt.state.zone_status = ZoneStatus.NORMAL

        controller.update_status(
            now=NOW + timedelta(seconds=5), has_pending_entities=False
        )
        assert controller.status == ControllerStatus.NORMAL
