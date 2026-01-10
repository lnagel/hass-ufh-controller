"""Tests for Coordinator failure handling."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sqlalchemy.exc import OperationalError

from custom_components.ufh_controller.const import (
    FAIL_SAFE_TIMEOUT,
    FAILURE_NOTIFICATION_THRESHOLD,
    ControllerStatus,
    ZoneStatus,
)
from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)


class TestCoordinatorFailureTracking:
    """Test coordinator failure tracking."""

    async def test_initial_status_is_normal(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that coordinator starts in normal status."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        assert coordinator.status == ControllerStatus.NORMAL
        assert coordinator.consecutive_failures == 0
        assert coordinator.last_successful_update is None

    async def test_record_success_updates_status(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that successful update records correctly."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Simulate recording success
        coordinator._record_success()

        assert coordinator.status == ControllerStatus.NORMAL
        assert coordinator.consecutive_failures == 0
        assert coordinator.last_successful_update is not None

    async def test_record_failure_increments_counter(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that failures increment counter."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        coordinator._record_failure(critical=True)
        assert coordinator.consecutive_failures == 1

        coordinator._record_failure(critical=True)
        assert coordinator.consecutive_failures == 2

    async def test_record_success_resets_failures(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that success resets failure counter."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Record some failures
        coordinator._record_failure(critical=True)
        coordinator._record_failure(critical=True)
        assert coordinator.consecutive_failures == 2

        # Success should reset
        coordinator._record_success()
        assert coordinator.consecutive_failures == 0

    async def test_critical_failure_sets_degraded_status(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that critical failure sets degraded status."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        coordinator._record_failure(critical=True)

        assert coordinator.status == ControllerStatus.DEGRADED

    async def test_non_critical_failure_sets_degraded_from_normal(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that non-critical failure sets degraded status from normal."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        assert coordinator.status == ControllerStatus.NORMAL

        coordinator._record_failure(critical=False)

        assert coordinator.status == ControllerStatus.DEGRADED
        assert coordinator.consecutive_failures == 1

    async def test_notification_created_after_threshold(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that notification is created after threshold failures."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Record failures up to threshold
        for _ in range(FAILURE_NOTIFICATION_THRESHOLD):
            coordinator._record_failure(critical=True)

        # Should have set notification_created flag
        assert coordinator._notification_created is True

    async def test_notification_not_duplicated(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that notification flag is only set once."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Record failures past threshold
        for _ in range(FAILURE_NOTIFICATION_THRESHOLD):
            coordinator._record_failure(critical=True)

        assert coordinator._notification_created is True

        # Record more failures - flag should remain True
        for _ in range(5):
            coordinator._record_failure(critical=True)

        assert coordinator._notification_created is True

    async def test_notification_dismissed_on_recovery(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that notification flag is cleared when controller recovers."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Create notification
        for _ in range(FAILURE_NOTIFICATION_THRESHOLD):
            coordinator._record_failure(critical=True)

        assert coordinator._notification_created is True

        # Recover
        coordinator._record_success()

        # Should clear notification flag
        assert coordinator._notification_created is False

    async def test_fail_safe_not_activated_immediately(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that fail-safe is not activated immediately on failure."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Single failure should not trigger fail-safe
        coordinator._record_failure(critical=True)

        assert coordinator.status != ControllerStatus.FAIL_SAFE
        assert coordinator._fail_safe_activated is False

    async def test_fail_safe_activated_after_timeout(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that fail-safe is activated after 1 hour timeout."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Set last successful update to more than 1 hour ago
        coordinator._last_successful_update = datetime.now(UTC) - timedelta(
            seconds=FAIL_SAFE_TIMEOUT + 60
        )

        # Record failure - should trigger fail-safe
        coordinator._record_failure(critical=True)

        assert coordinator.status == ControllerStatus.FAIL_SAFE
        assert coordinator._fail_safe_activated is True

    async def test_recovery_from_fail_safe(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that controller recovers from fail-safe mode."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Put into fail-safe mode
        coordinator._last_successful_update = datetime.now(UTC) - timedelta(
            seconds=FAIL_SAFE_TIMEOUT + 60
        )
        coordinator._record_failure(critical=True)
        assert coordinator.status == ControllerStatus.FAIL_SAFE

        # Recover
        coordinator._record_success()

        assert coordinator.status == ControllerStatus.NORMAL
        assert coordinator._fail_safe_activated is False

    async def test_state_dict_includes_controller_status(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that state dict includes controller status information."""
        mock_config_entry.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        state_dict = coordinator._build_state_dict()

        assert "controller_status" in state_dict
        assert state_dict["controller_status"] == "normal"
        assert "consecutive_failures" in state_dict
        assert state_dict["consecutive_failures"] == 0
        assert "last_successful_update" in state_dict


class TestCoordinatorUpdateZoneFailure:
    """Test coordinator _update_zone failure handling."""

    async def test_period_state_failure_sets_zone_degraded(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that period_state query failure sets zone to degraded."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Set observation_start to make it timezone-aware
        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        # Make the query fail with a SQLAlchemy error
        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(
            side_effect=OperationalError("statement", {}, Exception("DB unavailable"))
        )

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)

        # Zone should be in degraded state
        runtime = coordinator._controller.get_zone_runtime("zone1")
        assert runtime is not None
        assert runtime.state.zone_status == ZoneStatus.DEGRADED

    async def test_open_state_failure_uses_fallback(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that open_state query failure uses fallback from current state."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "on")  # Valve is ON

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Set observation_start to make it timezone-aware
        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        call_count = 0

        def mock_executor(*args: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (period_state_avg) succeeds
                return {"switch.zone1_valve": []}
            # Second call (open_state_avg) fails with SQLAlchemy error
            raise OperationalError("statement", {}, Exception("DB unavailable"))

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(side_effect=mock_executor)

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)

        # Zone should be in normal state (non-critical failure uses fallback)
        runtime = coordinator._controller.get_zone_runtime("zone1")
        assert runtime is not None
        assert runtime.state.zone_status == ZoneStatus.NORMAL

        # Verify fallback was used - zone should have open_state_avg = 1.0
        # since current valve state is "on"
        assert runtime.state.open_state_avg == 1.0

    async def test_open_state_fallback_with_unavailable_state(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that unavailable valve state falls back to 0.0 (closed)."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "unavailable")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        call_count = 0

        def mock_executor(*args: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"switch.zone1_valve": []}
            raise OperationalError("statement", {}, Exception("DB unavailable"))

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(side_effect=mock_executor)

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)

        runtime = coordinator._controller.get_zone_runtime("zone1")
        assert runtime is not None
        # Unavailable state should fall back to 0.0 (assume closed)
        assert runtime.state.open_state_avg == 0.0

    async def test_open_state_fallback_with_off_state(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that off valve state falls back to 0.0."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        call_count = 0

        def mock_executor(*args: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"switch.zone1_valve": []}
            raise OperationalError("statement", {}, Exception("DB unavailable"))

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(side_effect=mock_executor)

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)

        runtime = coordinator._controller.get_zone_runtime("zone1")
        assert runtime is not None
        assert runtime.state.open_state_avg == 0.0


class TestExecuteFailSafeActions:
    """Test fail-safe action execution."""

    async def test_execute_fail_safe_closes_valves(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that fail-safe mode closes all valves."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "on")

        # Mock switch service
        hass.services.async_register("switch", "turn_off", AsyncMock())
        hass.services.async_register("switch", "turn_on", AsyncMock())

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Execute fail-safe
        await coordinator._execute_fail_safe_actions()

        # Check valve state is set to off in zone runtime
        runtime = coordinator.controller.get_zone_runtime("zone1")
        assert runtime is not None
        assert runtime.state.valve_on is False


class TestCriticalFailureDuringUpdate:
    """Test critical failure handling during _async_update_data."""

    async def test_degraded_zone_continues_operating(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that degraded zone continues operating with fallback values."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Track if valve service was called
        valve_calls: list[str] = []

        async def track_switch_call(call: ServiceCall) -> None:
            valve_calls.append(call.service)

        hass.services.async_register("switch", "turn_on", track_switch_call)
        hass.services.async_register("switch", "turn_off", track_switch_call)

        # Make recorder query fail
        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(
            side_effect=OperationalError("statement", {}, Exception("DB unavailable"))
        )

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator.async_refresh()

        # Status should be degraded
        assert coordinator.status == ControllerStatus.DEGRADED

        # Zone should be degraded
        zone1 = coordinator._controller.get_zone_runtime("zone1")
        assert zone1 is not None
        assert zone1.state.zone_status == ZoneStatus.DEGRADED

        # Valve actions SHOULD still happen - this is the key change from old behavior
        # Zone continues operating with fallback values
        # (valve may turn on/off based on zone evaluation)

    async def test_zone_fail_safe_closes_valve_during_update(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that zone fail-safe mode forces valve closed during update."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "on")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Put zone into fail-safe by setting last_successful_update >1 hour ago
        zone1 = coordinator._controller.get_zone_runtime("zone1")
        assert zone1 is not None
        zone1.state.last_successful_update = datetime.now(UTC) - timedelta(
            seconds=FAIL_SAFE_TIMEOUT + 60
        )
        # Also set zone_status to ensure it's in fail-safe
        zone1.state.zone_status = ZoneStatus.FAIL_SAFE

        # Track valve service calls
        valve_calls: list[str] = []

        async def track_switch_call(call: ServiceCall) -> None:
            valve_calls.append(call.service)

        hass.services.async_register("switch", "turn_on", track_switch_call)
        hass.services.async_register("switch", "turn_off", track_switch_call)

        # Make recorder succeed to allow update to complete
        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator.async_refresh()

        # Controller should be fail-safe because the single zone is in fail-safe
        assert coordinator.status == ControllerStatus.FAIL_SAFE

        # Zone fail-safe should have turned off the valve
        assert "turn_off" in valve_calls


class TestZoneIsolation:
    """Test zone-level fault isolation."""

    async def test_single_zone_failure_does_not_affect_other_zones(
        self,
        hass: HomeAssistant,
        mock_config_entry_multiple_zones: MockConfigEntry,
    ) -> None:
        """Test that one zone's failure doesn't block other zones."""
        mock_config_entry_multiple_zones.add_to_hass(hass)
        # Zone 1 has valid temp, zone 2 has unavailable temp
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("sensor.zone2_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("switch.zone2_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_multiple_zones
        )

        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        # Make recorder succeed for both zones
        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)
            await coordinator._update_zone("zone2", now, 60.0)

        # Zone 1 should be normal (has valid temp)
        zone1 = coordinator._controller.get_zone_runtime("zone1")
        assert zone1 is not None
        assert zone1.state.zone_status == ZoneStatus.NORMAL

        # Zone 2 should be degraded (temp unavailable)
        zone2 = coordinator._controller.get_zone_runtime("zone2")
        assert zone2 is not None
        assert zone2.state.zone_status == ZoneStatus.DEGRADED

    async def test_zone_fail_safe_after_one_hour(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that zone enters fail-safe after 1 hour of failures."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        # Set zone's last_successful_update to more than 1 hour ago
        zone1 = coordinator._controller.get_zone_runtime("zone1")
        assert zone1 is not None
        zone1.state.last_successful_update = datetime.now(UTC) - timedelta(
            seconds=FAIL_SAFE_TIMEOUT + 60
        )

        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)

        # Zone should be in fail-safe
        assert zone1.state.zone_status == ZoneStatus.FAIL_SAFE

    async def test_zone_fail_safe_closes_only_that_zone(
        self,
        hass: HomeAssistant,
        mock_config_entry_multiple_zones: MockConfigEntry,
    ) -> None:
        """Test that zone fail-safe only closes that zone's valve."""
        mock_config_entry_multiple_zones.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("sensor.zone2_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("switch.zone2_valve", "on")

        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_multiple_zones
        )

        # Set zone2's last_successful_update to more than 1 hour ago
        zone2 = coordinator._controller.get_zone_runtime("zone2")
        assert zone2 is not None
        zone2.state.last_successful_update = datetime.now(UTC) - timedelta(
            seconds=FAIL_SAFE_TIMEOUT + 60
        )

        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator._update_zone("zone1", now, 60.0)
            await coordinator._update_zone("zone2", now, 60.0)

        # Zone 1 should be normal
        zone1 = coordinator._controller.get_zone_runtime("zone1")
        assert zone1 is not None
        assert zone1.state.zone_status == ZoneStatus.NORMAL

        # Zone 2 should be in fail-safe
        assert zone2.state.zone_status == ZoneStatus.FAIL_SAFE

    async def test_controller_never_fail_safe_if_one_zone_works(
        self,
        hass: HomeAssistant,
        mock_config_entry_multiple_zones: MockConfigEntry,
    ) -> None:
        """Test controller never enters fail-safe if at least one zone is working."""
        mock_config_entry_multiple_zones.add_to_hass(hass)
        # Zone 1 works, zone 2 is in fail-safe
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("sensor.zone2_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("switch.zone2_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_multiple_zones
        )

        # Put zone2 into fail-safe
        zone2 = coordinator._controller.get_zone_runtime("zone2")
        assert zone2 is not None
        zone2.state.zone_status = ZoneStatus.FAIL_SAFE

        # Update controller status
        coordinator._update_controller_status_from_zones()

        # Controller should be degraded, NOT fail-safe
        assert coordinator.status == ControllerStatus.DEGRADED

    async def test_controller_fail_safe_only_when_all_zones_fail(
        self,
        hass: HomeAssistant,
        mock_config_entry_multiple_zones: MockConfigEntry,
    ) -> None:
        """Test controller fail-safe requires all zones in fail-safe."""
        mock_config_entry_multiple_zones.add_to_hass(hass)

        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_multiple_zones
        )

        # Put both zones into fail-safe
        zone1 = coordinator._controller.get_zone_runtime("zone1")
        zone2 = coordinator._controller.get_zone_runtime("zone2")
        assert zone1 is not None
        assert zone2 is not None
        zone1.state.zone_status = ZoneStatus.FAIL_SAFE
        zone2.state.zone_status = ZoneStatus.FAIL_SAFE

        # Update controller status
        coordinator._update_controller_status_from_zones()

        # NOW controller should be in fail-safe
        assert coordinator.status == ControllerStatus.FAIL_SAFE

    async def test_zone_recovery_from_degraded(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test zone recovers from degraded status when temp becomes available."""
        mock_config_entry.add_to_hass(hass)
        # Start with unavailable temp
        hass.states.async_set("sensor.zone1_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        now = datetime.now(UTC)
        coordinator._controller.state.observation_start = now - timedelta(hours=1)

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            # First update - zone should be degraded
            await coordinator._update_zone("zone1", now, 60.0)

        zone1 = coordinator._controller.get_zone_runtime("zone1")
        assert zone1 is not None
        assert zone1.state.zone_status == ZoneStatus.DEGRADED

        # Fix the temperature sensor
        hass.states.async_set("sensor.zone1_temp", "21.0")

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            # Second update - zone should recover
            await coordinator._update_zone("zone1", now + timedelta(seconds=60), 60.0)

        assert zone1.state.zone_status == ZoneStatus.NORMAL

    async def test_summer_mode_forced_auto_when_zone_in_fail_safe(
        self,
        hass: HomeAssistant,
        mock_config_entry_multiple_zones: MockConfigEntry,
    ) -> None:
        """Test summer mode is forced to auto when any zone is in fail-safe."""
        mock_config_entry_multiple_zones.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("sensor.zone2_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("switch.zone2_valve", "off")
        hass.states.async_set("select.summer_mode", "winter")

        # Register select service
        summer_mode_calls: list[str] = []

        async def track_select_call(call: ServiceCall) -> None:
            summer_mode_calls.append(call.data["option"])

        hass.services.async_register("select", "select_option", track_select_call)

        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_multiple_zones
        )

        # Put zone2 into fail-safe
        zone2 = coordinator._controller.get_zone_runtime("zone2")
        assert zone2 is not None
        zone2.state.zone_status = ZoneStatus.FAIL_SAFE

        # Call summer mode update with heat_request=True
        # Without fail-safe zone, this would set to "winter"
        # But with fail-safe zone, it should force to "auto"
        await coordinator._update_summer_mode(heat_request=True)

        assert "auto" in summer_mode_calls

    async def test_state_dict_includes_zone_status(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test state dict includes zone status."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

        state_dict = coordinator._build_state_dict()

        # Check zone status is included
        assert "zones" in state_dict
        assert "zone1" in state_dict["zones"]
        assert "zone_status" in state_dict["zones"]["zone1"]
        assert state_dict["zones"]["zone1"]["zone_status"] == "normal"

        # Check zone counts
        assert "zones_degraded" in state_dict
        assert "zones_fail_safe" in state_dict
