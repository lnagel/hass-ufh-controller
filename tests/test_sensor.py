"""Tests for UFH Controller sensor platform."""

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def sensor_entity_prefix() -> str:
    """Return the sensor entity ID prefix for zone1."""
    return "sensor.test_zone_1"


async def test_duty_cycle_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_entity_prefix: str,
) -> None:
    """Test duty cycle sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_duty_cycle")
    assert state is not None


async def test_pid_error_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_entity_prefix: str,
) -> None:
    """Test PID error sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_pid_error")
    assert state is not None


async def test_pid_proportional_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_entity_prefix: str,
) -> None:
    """Test PID proportional sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_pid_proportional")
    assert state is not None


async def test_pid_integral_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_entity_prefix: str,
) -> None:
    """Test PID integral sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_pid_integral")
    assert state is not None


async def test_requesting_zones_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test requesting zones sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_controller_requesting_zones")
    assert state is not None


async def test_sensor_count_with_zone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test correct number of sensors are created with one zone."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # 4 zone sensors (duty_cycle, pid_error, pid_proportional, pid_integral)
    # + 1 controller sensor (requesting_zones)
    # = 5 total sensors
    states = hass.states.async_entity_ids(SENSOR_DOMAIN)
    assert len(states) == 5


async def test_no_zone_sensors_without_zones(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test only controller sensor created when no zones configured."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    # Only requesting_zones sensor should exist
    states = hass.states.async_entity_ids(SENSOR_DOMAIN)
    assert len(states) == 1
