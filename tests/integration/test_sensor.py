"""Tests for Underfloor Heating Controller sensor platform."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    FAIL_SAFE_TIMEOUT,
    ZoneStatus,
)


@pytest.fixture
def sensor_entity_prefix() -> str:
    """Return the sensor entity ID prefix for zone1."""
    return "sensor.test_zone_1"


@pytest.mark.parametrize(
    "sensor_name",
    [
        "duty_cycle",
        "pid_error",
        "pid_proportional",
        "pid_integral",
        "pid_derivative",
        "remaining_duration",
    ],
)
async def test_zone_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_entity_prefix: str,
    sensor_name: str,
) -> None:
    """Test zone-level sensors are created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_{sensor_name}")
    assert state is not None


@pytest.mark.parametrize(
    "sensor_name",
    ["zones_flowing", "zones_heating", "zones_window"],
)
async def test_controller_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_name: str,
) -> None:
    """Test controller-level sensors are created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"sensor.test_controller_{sensor_name}")
    assert state is not None


async def test_sensor_count_with_zone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test correct number of sensors are created with one zone."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # 6 zone sensors + 3 controller sensors (zones_flowing/heating/window) = 9 total
    states = hass.states.async_entity_ids(SENSOR_DOMAIN)
    assert len(states) == 9


async def test_no_zone_sensors_without_zones(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test only controller sensor created when no zones configured."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    # Only controller sensors (zones_flowing/heating/window) should exist
    states = hass.states.async_entity_ids(SENSOR_DOMAIN)
    assert len(states) == 3


async def test_zone_sensor_unavailable_during_fail_safe(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    sensor_entity_prefix: str,
) -> None:
    """Test zone sensors are unavailable during FAIL_SAFE status."""
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

    # All zone sensors should be unavailable during FAIL_SAFE
    for sensor_suffix in [
        "duty_cycle",
        "pid_error",
        "pid_proportional",
        "pid_integral",
        "pid_derivative",
        "remaining_duration",
    ]:
        state = hass.states.get(f"{sensor_entity_prefix}_{sensor_suffix}")
        assert state is not None, f"Sensor {sensor_suffix} not found"
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor {sensor_suffix} should be unavailable during FAIL_SAFE, "
            f"got {state.state}"
        )


async def test_supply_coefficient_sensor_created_with_supply_entity(
    hass: HomeAssistant,
    mock_config_entry_with_supply_temp: MockConfigEntry,
) -> None:
    """Test supply_coefficient sensor is created when supply_temp_entity is set."""
    # Set up the supply temperature sensor entity
    hass.states.async_set("sensor.supply_temp", "45.0")
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("switch.zone1_valve", "off")

    mock_config_entry_with_supply_temp.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_supply_temp.entry_id)
    await hass.async_block_till_done()

    # Supply coefficient sensor should exist for zone1
    state = hass.states.get("sensor.test_zone_1_supply_coefficient")
    assert state is not None


async def test_supply_coefficient_sensor_not_created_without_supply_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test supply_coefficient sensor is NOT created when no supply_temp_entity."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Supply coefficient sensor should NOT exist
    state = hass.states.get("sensor.test_zone_1_supply_coefficient")
    assert state is None


async def test_supply_temp_invalid_state_returns_none(
    hass: HomeAssistant,
    mock_config_entry_with_supply_temp: MockConfigEntry,
) -> None:
    """Test that invalid supply temp state (non-numeric) is handled gracefully."""
    # Set up the supply temperature sensor with an invalid state
    hass.states.async_set("sensor.supply_temp", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("switch.zone1_valve", "off")

    mock_config_entry_with_supply_temp.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_supply_temp.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_supply_temp.runtime_data.coordinator

    # _get_supply_temp should return None when state is non-numeric
    result = coordinator._get_supply_temp()
    assert result is None
