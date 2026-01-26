"""Tests for Underfloor Heating Controller binary sensor platform."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import FAIL_SAFE_TIMEOUT, ZoneStatus


@pytest.fixture
def controller_status_entity_id() -> str:
    """Return the controller status binary sensor entity ID."""
    return "binary_sensor.test_controller_status"


async def test_controller_status_binary_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    controller_status_entity_id: str,
) -> None:
    """Test controller status binary sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(controller_status_entity_id)
    assert state is not None


async def test_controller_status_extra_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    controller_status_entity_id: str,
) -> None:
    """Test controller status binary sensor has correct extra attributes."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(controller_status_entity_id)
    assert state is not None
    attrs = state.attributes

    # Check extra attributes are present with correct values
    assert "controller_status" in attrs
    assert attrs["controller_status"] == "normal"
    assert "zones_degraded" in attrs
    assert attrs["zones_degraded"] == 0
    assert "zones_fail_safe" in attrs
    assert attrs["zones_fail_safe"] == 0


async def test_controller_status_off_when_normal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    controller_status_entity_id: str,
) -> None:
    """Test controller status is OFF when operating normally (no problem)."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(controller_status_entity_id)
    assert state is not None
    # Binary sensor with PROBLEM device class: OFF = no problem
    assert state.state == "off"


async def test_zone_blocked_binary_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test zone blocked binary sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_zone_1_blocked")
    assert state is not None
    # Zone should not be blocked by default
    assert state.state == "off"


async def test_zone_heat_request_binary_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test zone heat request binary sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_zone_1_heat_request")
    assert state is not None


async def test_no_binary_sensors_without_zones(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test no zone binary sensors created when no zones configured."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    # Only controller status should exist, no zone sensors
    states = hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN)
    # Controller status sensor should still exist
    assert "binary_sensor.test_controller_status" in states
    # No zone sensors
    assert not any("blocked" in s for s in states)
    assert not any("heat_request" in s for s in states)


async def test_controller_status_off_when_initializing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    controller_status_entity_id: str,
) -> None:
    """Test controller status is OFF during initialization (not a problem)."""
    # Note: No mock_temp_sensor fixture, so zone stays in INITIALIZING
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(controller_status_entity_id)
    assert state is not None
    # Binary sensor with PROBLEM device class: OFF = no problem
    # Initializing is NOT a problem, so sensor should be OFF
    assert state.state == "off"
    # But status attribute should show "initializing"
    assert state.attributes["controller_status"] == "initializing"


async def test_zone_binary_sensor_available_during_initializing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test zone binary sensors are available during INITIALIZING status."""
    # Note: No mock_temp_sensor fixture, so zone stays in INITIALIZING
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Both zone binary sensors should be available during initialization
    blocked_state = hass.states.get("binary_sensor.test_zone_1_blocked")
    assert blocked_state is not None
    assert blocked_state.state in ("on", "off")

    heat_request_state = hass.states.get("binary_sensor.test_zone_1_heat_request")
    assert heat_request_state is not None
    assert heat_request_state.state in ("on", "off")


async def test_zone_binary_sensor_available_during_normal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test zone binary sensors are available during NORMAL status."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Both zone binary sensors should be available (have actual state)
    blocked_state = hass.states.get("binary_sensor.test_zone_1_blocked")
    assert blocked_state is not None
    assert blocked_state.state in ("on", "off")

    heat_request_state = hass.states.get("binary_sensor.test_zone_1_heat_request")
    assert heat_request_state is not None
    assert heat_request_state.state in ("on", "off")


async def test_zone_binary_sensor_available_during_degraded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test zone binary sensors are available during DEGRADED status."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get coordinator from config entry
    coordinator = mock_config_entry.runtime_data.coordinator

    # Zone should be NORMAL now
    zone1 = coordinator._controller.get_zone_runtime("zone1")
    assert zone1 is not None
    assert zone1.state.zone_status == ZoneStatus.NORMAL

    # Set to DEGRADED
    zone1.state.zone_status = ZoneStatus.DEGRADED
    coordinator.async_set_updated_data(coordinator._build_state_dict())

    await hass.async_block_till_done()

    # Binary sensors should still be available during DEGRADED
    blocked_state = hass.states.get("binary_sensor.test_zone_1_blocked")
    assert blocked_state is not None
    assert blocked_state.state in ("on", "off")


async def test_zone_binary_sensor_unavailable_during_fail_safe(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test zone binary sensors are unavailable during FAIL_SAFE status."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get coordinator from config entry
    coordinator = mock_config_entry.runtime_data.coordinator

    # Put zone into fail-safe
    zone1 = coordinator._controller.get_zone_runtime("zone1")
    assert zone1 is not None
    zone1.state.zone_status = ZoneStatus.FAIL_SAFE
    zone1.state.last_successful_update = datetime.now(UTC) - timedelta(
        seconds=FAIL_SAFE_TIMEOUT + 60
    )
    coordinator.async_set_updated_data(coordinator._build_state_dict())

    await hass.async_block_till_done()

    # Binary sensors should be unavailable during FAIL_SAFE
    blocked_state = hass.states.get("binary_sensor.test_zone_1_blocked")
    assert blocked_state is not None
    assert blocked_state.state == STATE_UNAVAILABLE

    heat_request_state = hass.states.get("binary_sensor.test_zone_1_heat_request")
    assert heat_request_state is not None
    assert heat_request_state.state == STATE_UNAVAILABLE


async def test_flush_request_binary_sensor_created_with_dhw(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test flush_request binary sensor is created when DHW entity is configured."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_controller_flush_request")
    assert state is not None


async def test_flush_request_not_created_without_dhw(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test flush_request sensor is NOT created when DHW entity is not configured."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_controller_flush_request")
    assert state is None


async def test_flush_request_off_when_flush_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test flush_request is OFF when flush_enabled is False."""
    hass.states.async_set("binary_sensor.dhw_active", "on")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set flush NOT enabled
    coordinator.controller.state.flush_enabled = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_controller_flush_request")
    assert state is not None
    assert state.state == "off"


async def test_flush_request_off_during_dhw_with_flush_enabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test flush_request is OFF during DHW active."""
    hass.states.async_set("binary_sensor.dhw_active", "on")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set flush enabled
    coordinator.controller.state.flush_enabled = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_controller_flush_request")
    assert state is not None
    assert state.state == "off"


async def test_flush_request_on_during_post_dhw_period(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """Test flush_request is ON during post-DHW flush period."""
    hass.states.async_set("binary_sensor.dhw_active", "off")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set flush_request to True (simulates post-DHW flush period)
    coordinator.controller.state.flush_enabled = True
    coordinator.controller.state.flush_request = True
    coordinator.async_set_updated_data(coordinator._build_state_dict())
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_controller_flush_request")
    assert state is not None
    assert state.state == "on"
