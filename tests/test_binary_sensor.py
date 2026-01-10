"""Tests for Underfloor Heating Controller binary sensor platform."""

import pytest
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


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
