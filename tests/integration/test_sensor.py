"""Tests for Underfloor Heating Controller sensor platform."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    FAIL_SAFE_TIMEOUT,
    PID_ERROR_AT_SETPOINT_THRESHOLD,
    ZoneStatus,
)
from custom_components.ufh_controller.core.pid import PIDState


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


async def test_pid_derivative_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor_entity_prefix: str,
) -> None:
    """Test PID derivative sensor is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_pid_derivative")
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

    # 5 zone sensors + 1 controller sensor (requesting_zones) = 6 total
    states = hass.states.async_entity_ids(SENSOR_DOMAIN)
    assert len(states) == 6


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
    ]:
        state = hass.states.get(f"{sensor_entity_prefix}_{sensor_suffix}")
        assert state is not None, f"Sensor {sensor_suffix} not found"
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor {sensor_suffix} should be unavailable during FAIL_SAFE, "
            f"got {state.state}"
        )


@pytest.mark.parametrize(
    ("error_value", "expected_icon"),
    [
        (None, "mdi:thermometer-off"),
        (1.0, "mdi:thermometer-chevron-up"),  # Cold, needs heating
        (PID_ERROR_AT_SETPOINT_THRESHOLD + 0.01, "mdi:thermometer-chevron-up"),
        (-1.0, "mdi:thermometer-chevron-down"),  # Warm, above setpoint
        (-PID_ERROR_AT_SETPOINT_THRESHOLD - 0.01, "mdi:thermometer-chevron-down"),
        (0.0, "mdi:thermometer-check"),  # At setpoint
        (PID_ERROR_AT_SETPOINT_THRESHOLD - 0.01, "mdi:thermometer-check"),
        (-PID_ERROR_AT_SETPOINT_THRESHOLD + 0.01, "mdi:thermometer-check"),
    ],
)
async def test_pid_error_sensor_icon(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    sensor_entity_prefix: str,
    error_value: float | None,
    expected_icon: str,
) -> None:
    """Test PID error sensor icon changes based on error value."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    zone1 = coordinator._controller.get_zone_runtime("zone1")
    assert zone1 is not None

    # Set the error value in the PID state (where coordinator reads it from)
    # PIDState is frozen, so we need to replace it entirely
    old_state = zone1.pid.state
    zone1.pid._state = (
        PIDState(
            error=error_value if error_value is not None else 0.0,
            p_term=old_state.p_term if old_state else 0.0,
            i_term=old_state.i_term if old_state else 0.0,
            d_term=old_state.d_term if old_state else 0.0,
            duty_cycle=old_state.duty_cycle if old_state else 0.0,
        )
        if error_value is not None
        else None
    )
    coordinator.async_set_updated_data(coordinator._build_state_dict())
    await hass.async_block_till_done()

    state = hass.states.get(f"{sensor_entity_prefix}_pid_error")
    assert state is not None
    assert state.attributes.get("icon") == expected_icon
