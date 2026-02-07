"""
Tests for outdoor temperature initialization in the coordinator.

When an outdoor temperature sensor is configured, the controller waits for it
during initialization (up to INITIALIZING_TIMEOUT). If the sensor remains
unavailable after the timeout, the controller proceeds with the fallback supply
target temperature and reports DEGRADED status.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_SUPPLY_TARGET_TEMP,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
    DEFAULT_TIMING,
    DOMAIN,
    INITIALIZING_TIMEOUT,
    SUBENTRY_TYPE_ZONE,
    ControllerStatus,
)
from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)
from tests.conftest import MOCK_ZONE_DATA


@pytest.fixture
def mock_config_entry_with_outdoor_temp() -> MockConfigEntry:
    """Return a mock config entry with outdoor temperature sensor configured."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller Outdoor",
        data={
            "name": "Test Controller Outdoor",
            "controller_id": "test_outdoor",
            "outdoor_temp_entity": "sensor.outdoor_temp",
            "outdoor_temp_warm": DEFAULT_OUTDOOR_TEMP_WARM,
            "outdoor_temp_cold": DEFAULT_OUTDOOR_TEMP_COLD,
            "supply_temp_warm": DEFAULT_SUPPLY_TEMP_WARM,
            "supply_temp_cold": DEFAULT_SUPPLY_TEMP_COLD,
            "supply_target_temp": DEFAULT_SUPPLY_TARGET_TEMP,
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_outdoor",
        unique_id="test_outdoor",
        subentries_data=[
            {
                "data": MOCK_ZONE_DATA,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )


class TestOutdoorTempInitWaiting:
    """Test controller waits for outdoor temp during initialization."""

    async def test_stays_initializing_when_outdoor_temp_unavailable(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller stays INITIALIZING when outdoor temp sensor unavailable."""
        # Zone temp available, outdoor temp NOT available
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        # No outdoor temp state set

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator

        # Even though zone temp is available, controller waits for outdoor temp
        assert coordinator.status == ControllerStatus.INITIALIZING

    async def test_transitions_to_normal_when_outdoor_temp_arrives(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller transitions to NORMAL when outdoor temp becomes available."""
        # Zone temp available, outdoor temp available
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator

        assert coordinator.status == ControllerStatus.NORMAL

    async def test_transitions_to_normal_when_outdoor_temp_arrives_after_delay(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller transitions to NORMAL when outdoor temp arrives within timeout."""
        # Zone temp available, no outdoor temp yet
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.INITIALIZING

        # Outdoor temp arrives
        hass.states.async_set("sensor.outdoor_temp", "5.0")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.status == ControllerStatus.NORMAL

    async def test_no_outdoor_sensor_configured_no_effect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Without outdoor temp sensor, controller init is unaffected."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Controller should be NORMAL since zone has temp and no outdoor temp required
        assert coordinator.status == ControllerStatus.NORMAL


class TestOutdoorTempInitTimeout:
    """Test controller behavior after outdoor temp init timeout."""

    async def test_degrades_after_timeout(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller reports DEGRADED after init timeout with no outdoor temp."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_with_outdoor_temp
        )

        # Simulate init start in the past (beyond timeout)
        past_time = datetime.now(UTC) - timedelta(seconds=INITIALIZING_TIMEOUT + 10)
        coordinator._init_start = past_time

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # After timeout, controller should be DEGRADED (not INITIALIZING)
        assert coordinator.status == ControllerStatus.DEGRADED

    async def test_timeout_warning_logged_once(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Timeout warning is logged once when outdoor temp init times out."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_with_outdoor_temp
        )

        # Simulate init start in the past (beyond timeout)
        past_time = datetime.now(UTC) - timedelta(seconds=INITIALIZING_TIMEOUT + 10)
        coordinator._init_start = past_time

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            caplog.clear()
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # Warning should be logged
        timeout_warnings = [
            r for r in caplog.records if "initialization timeout" in r.message
        ]
        assert len(timeout_warnings) == 1
        assert coordinator._outdoor_temp_init_timed_out is True

        # Second refresh should NOT log again
        mock_recorder2 = MagicMock()
        mock_recorder2.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder2,
        ):
            caplog.clear()
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        timeout_warnings = [
            r for r in caplog.records if "initialization timeout" in r.message
        ]
        assert len(timeout_warnings) == 0

    async def test_uses_fallback_supply_target_after_timeout(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller uses fallback supply target when outdoor temp unavailable."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_with_outdoor_temp
        )

        # Simulate init start in the past (beyond timeout)
        past_time = datetime.now(UTC) - timedelta(seconds=INITIALIZING_TIMEOUT + 10)
        coordinator._init_start = past_time

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # Supply target should be the fallback value
        controller = coordinator.controller
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP
        assert controller.state.outdoor_temp is None


class TestOutdoorTempLostDuringOperation:
    """Test controller behavior when outdoor temp is lost during normal operation."""

    async def test_degrades_when_outdoor_temp_lost(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller reports DEGRADED when outdoor temp lost after normal operation."""
        # Start with everything available
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.NORMAL

        # Outdoor temp becomes unavailable
        hass.states.async_set("sensor.outdoor_temp", "unavailable")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.status == ControllerStatus.DEGRADED

    async def test_recovers_when_outdoor_temp_returns(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Controller recovers to NORMAL when outdoor temp returns."""
        # Start with everything available
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.NORMAL

        # Lose outdoor temp
        hass.states.async_set("sensor.outdoor_temp", "unavailable")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.status == ControllerStatus.DEGRADED

        # Outdoor temp returns
        hass.states.async_set("sensor.outdoor_temp", "8.0")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.status == ControllerStatus.NORMAL


class TestOutdoorTempStateDict:
    """Test outdoor_temp_unavailable in state dict and binary sensor attributes."""

    async def test_outdoor_temp_unavailable_true_in_state_dict(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """State dict includes outdoor_temp_unavailable=True when sensor missing."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator

        # Start normal
        controller_data = coordinator.data["controller"]
        assert controller_data["outdoor_temp_unavailable"] is False

        # Lose outdoor temp
        hass.states.async_set("sensor.outdoor_temp", "unavailable")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        controller_data = coordinator.data["controller"]
        assert controller_data["outdoor_temp_unavailable"] is True

    async def test_outdoor_temp_unavailable_false_without_sensor(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """State dict has outdoor_temp_unavailable=False when no sensor configured."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        controller_data = coordinator.data["controller"]
        assert controller_data["outdoor_temp_unavailable"] is False

    async def test_status_binary_sensor_attributes_include_outdoor_temp(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Status binary sensor attributes include outdoor_temp_unavailable."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.test_controller_outdoor_status")
        assert state is not None
        assert "outdoor_temp_unavailable" in state.attributes
        assert state.attributes["outdoor_temp_unavailable"] is False

    async def test_status_binary_sensor_shows_problem_when_outdoor_temp_lost(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Status binary sensor shows problem when outdoor temp unavailable."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        entity_id = "binary_sensor.test_controller_outdoor_status"

        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "off"  # No problem

        # Lose outdoor temp
        hass.states.async_set("sensor.outdoor_temp", "unavailable")
        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "on"  # Problem detected
        assert state.attributes["outdoor_temp_unavailable"] is True
        assert state.attributes["status"] == "degraded"


class TestOutdoorTempInitWithZoneStatus:
    """Test outdoor temp init interacts correctly with zone status."""

    async def test_zone_fail_safe_takes_precedence_over_outdoor_temp_init(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Zone FAIL_SAFE status is not downgraded by outdoor temp init."""
        # Both zone temp AND outdoor temp unavailable
        hass.states.async_set("sensor.zone1_temp", "unavailable")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        coordinator = UFHControllerDataUpdateCoordinator(
            hass, mock_config_entry_with_outdoor_temp
        )

        # Simulate far past init timeout so zone enters fail-safe
        past_time = datetime.now(UTC) - timedelta(seconds=INITIALIZING_TIMEOUT + 10)
        coordinator._init_start = past_time

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})

        # Force the zone's last_successful_update far in the past
        runtime = coordinator._controller.get_zone_runtime("zone1")
        runtime.state.last_successful_update = past_time

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # FAIL_SAFE should not be downgraded to DEGRADED
        assert coordinator.status == ControllerStatus.FAIL_SAFE

    async def test_zone_degraded_takes_precedence_during_outdoor_init(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Zone DEGRADED is not overridden by outdoor temp INITIALIZING."""
        # Zone temp available first, then becomes unavailable
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator

        # Zone becomes degraded (temp lost while controller was waiting for outdoor)
        hass.states.async_set("sensor.zone1_temp", "unavailable")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Should be DEGRADED (zone problem), not just INITIALIZING (outdoor wait)
        assert coordinator.status == ControllerStatus.DEGRADED


class TestOutdoorTempConfigReload:
    """Test outdoor temp init state reset on config reload."""

    async def test_reload_restarts_init_when_outdoor_temp_lost(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_outdoor_temp: MockConfigEntry,
    ) -> None:
        """Config reload resets outdoor temp tracking, re-entering init if needed."""
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_outdoor_temp.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_outdoor_temp.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_outdoor_temp.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.NORMAL
        assert coordinator._outdoor_temp_received is True

        # Outdoor temp becomes unavailable before reload
        hass.states.async_set("sensor.outdoor_temp", "unavailable")

        # Reload config - this resets tracking and triggers refresh
        await coordinator.async_reload_config()
        await hass.async_block_till_done()

        # After reload, controller should be back in INITIALIZING (waiting for
        # outdoor temp again) because the tracking was reset
        assert coordinator.status == ControllerStatus.INITIALIZING
        assert coordinator._outdoor_temp_received is False
