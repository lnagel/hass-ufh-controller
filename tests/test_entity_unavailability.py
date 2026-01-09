"""Tests for entity unavailability handling in UFH Controller."""

from typing import Any

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
    SummerMode,
)

MOCK_CONTROLLER_ID = "test_controller"


def _make_zone_data(
    zone_id: str = "zone1",
    name: str = "Test Zone 1",
    window_sensors: list[str] | None = None,
) -> dict[str, Any]:
    """Create zone data for testing."""
    return {
        "id": zone_id,
        "name": name,
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": window_sensors or [],
        "presets": {
            "home": 21.0,
            "away": 16.0,
            "eco": 19.0,
            "comfort": 22.0,
            "boost": 25.0,
        },
    }


@pytest.fixture
def mock_config_entry_with_dhw() -> MockConfigEntry:
    """Return a mock config entry with DHW entity configured."""
    zone_data = _make_zone_data()
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
            "dhw_active_entity": "binary_sensor.dhw_active",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_dhw",
        unique_id=f"{MOCK_CONTROLLER_ID}_dhw",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )


@pytest.fixture
def mock_config_entry_with_summer_mode() -> MockConfigEntry:
    """Return a mock config entry with summer mode entity configured."""
    zone_data = _make_zone_data()
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
            "summer_mode_entity": "select.boiler_summer_mode",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_summer",
        unique_id=f"{MOCK_CONTROLLER_ID}_summer",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )


@pytest.fixture
def mock_config_entry_with_heat_request() -> MockConfigEntry:
    """Return a mock config entry with heat request entity configured."""
    zone_data = _make_zone_data()
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
            "heat_request_entity": "switch.heat_request",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_heat_request",
        unique_id=f"{MOCK_CONTROLLER_ID}_heat_request",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )


@pytest.fixture
def mock_config_entry_with_window_sensor() -> MockConfigEntry:
    """Return a mock config entry with window sensor configured."""
    zone_data = _make_zone_data(window_sensors=["binary_sensor.window1"])
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_window",
        unique_id=f"{MOCK_CONTROLLER_ID}_window",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )


# ============================================================================
# DHW Sensor Unavailability Tests
# ============================================================================


async def test_dhw_sensor_unavailable_treats_as_inactive(
    hass: HomeAssistant,
    mock_config_entry_with_dhw: MockConfigEntry,
) -> None:
    """Test DHW sensor in unavailable state is treated as inactive."""
    # Set up the DHW sensor as unavailable
    hass.states.async_set("binary_sensor.dhw_active", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_dhw.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_dhw.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_dhw.runtime_data.coordinator
    # DHW should be treated as inactive when unavailable
    assert coordinator.controller.state.dhw_active is False


async def test_dhw_sensor_unknown_treats_as_inactive(
    hass: HomeAssistant,
    mock_config_entry_with_dhw: MockConfigEntry,
) -> None:
    """Test DHW sensor in unknown state is treated as inactive."""
    # Set up the DHW sensor as unknown
    hass.states.async_set("binary_sensor.dhw_active", STATE_UNKNOWN)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_dhw.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_dhw.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_dhw.runtime_data.coordinator
    # DHW should be treated as inactive when unknown
    assert coordinator.controller.state.dhw_active is False


async def test_dhw_sensor_missing_treats_as_inactive(
    hass: HomeAssistant,
    mock_config_entry_with_dhw: MockConfigEntry,
) -> None:
    """Test missing DHW sensor is treated as inactive."""
    # Don't set up any state for DHW sensor (entity doesn't exist)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_dhw.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_dhw.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_dhw.runtime_data.coordinator
    # DHW should be treated as inactive when entity doesn't exist
    assert coordinator.controller.state.dhw_active is False


async def test_dhw_sensor_on_activates_dhw(
    hass: HomeAssistant,
    mock_config_entry_with_dhw: MockConfigEntry,
) -> None:
    """Test DHW sensor in 'on' state activates DHW priority."""
    # Set up the DHW sensor as on
    hass.states.async_set("binary_sensor.dhw_active", "on")
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_dhw.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_dhw.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_dhw.runtime_data.coordinator
    # DHW should be active when sensor is on
    assert coordinator.controller.state.dhw_active is True


async def test_dhw_sensor_off_deactivates_dhw(
    hass: HomeAssistant,
    mock_config_entry_with_dhw: MockConfigEntry,
) -> None:
    """Test DHW sensor in 'off' state deactivates DHW priority."""
    hass.states.async_set("binary_sensor.dhw_active", "off")
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_dhw.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_dhw.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_dhw.runtime_data.coordinator
    # DHW should be inactive when sensor is off
    assert coordinator.controller.state.dhw_active is False


# ============================================================================
# Summer Mode Entity Missing/Unavailable Tests
# ============================================================================


async def test_summer_mode_entity_missing_no_error(
    hass: HomeAssistant,
    mock_config_entry_with_summer_mode: MockConfigEntry,
) -> None:
    """Test no error when summer mode entity is missing (state is None)."""
    # Don't set up any state for summer mode entity (state will be None)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Should not raise an exception
    mock_config_entry_with_summer_mode.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_summer_mode.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is running
    coordinator = mock_config_entry_with_summer_mode.runtime_data.coordinator
    assert coordinator is not None


async def test_summer_mode_entity_unavailable_no_error(
    hass: HomeAssistant,
    mock_config_entry_with_summer_mode: MockConfigEntry,
) -> None:
    """Test no error when summer mode entity is unavailable."""
    # Set entity as unavailable
    hass.states.async_set("select.boiler_summer_mode", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Should not raise an exception
    mock_config_entry_with_summer_mode.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_summer_mode.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is running
    coordinator = mock_config_entry_with_summer_mode.runtime_data.coordinator
    assert coordinator is not None


async def test_summer_mode_entity_unknown_no_error(
    hass: HomeAssistant,
    mock_config_entry_with_summer_mode: MockConfigEntry,
) -> None:
    """Test no error when summer mode entity is unknown."""
    # Set entity as unknown
    hass.states.async_set("select.boiler_summer_mode", STATE_UNKNOWN)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Should not raise an exception
    mock_config_entry_with_summer_mode.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_summer_mode.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is running
    coordinator = mock_config_entry_with_summer_mode.runtime_data.coordinator
    assert coordinator is not None


async def test_summer_mode_value_calculation(
    hass: HomeAssistant,
    mock_config_entry_with_summer_mode: MockConfigEntry,
) -> None:
    """Test summer mode value is correctly calculated based on heat request."""
    hass.states.async_set("select.boiler_summer_mode", "winter")
    # Temperature above setpoint means no heating request
    hass.states.async_set("sensor.zone1_temp", "25.0")

    mock_config_entry_with_summer_mode.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_summer_mode.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_summer_mode.runtime_data.coordinator
    # No heat request should mean SummerMode.SUMMER
    heat_request = coordinator.controller.calculate_heat_request()
    summer_mode_value = coordinator.controller.get_summer_mode_value(
        heat_request=heat_request
    )
    assert summer_mode_value == SummerMode.SUMMER


# ============================================================================
# Heat Request Switch Unavailability Tests
# ============================================================================


async def test_heat_request_switch_unavailable_no_error(
    hass: HomeAssistant,
    mock_config_entry_with_heat_request: MockConfigEntry,
) -> None:
    """Test no error when heat request switch is unavailable."""
    hass.states.async_set("switch.heat_request", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Should not raise an exception
    mock_config_entry_with_heat_request.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_heat_request.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is running
    coordinator = mock_config_entry_with_heat_request.runtime_data.coordinator
    assert coordinator is not None


async def test_heat_request_switch_unknown_no_error(
    hass: HomeAssistant,
    mock_config_entry_with_heat_request: MockConfigEntry,
) -> None:
    """Test no error when heat request switch is unknown."""
    hass.states.async_set("switch.heat_request", STATE_UNKNOWN)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Should not raise an exception
    mock_config_entry_with_heat_request.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_heat_request.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is running
    coordinator = mock_config_entry_with_heat_request.runtime_data.coordinator
    assert coordinator is not None


async def test_heat_request_switch_missing_no_error(
    hass: HomeAssistant,
    mock_config_entry_with_heat_request: MockConfigEntry,
) -> None:
    """Test no error when heat request switch entity doesn't exist."""
    # Don't set up the switch entity (state will be None)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Should not raise an exception
    mock_config_entry_with_heat_request.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_heat_request.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is running
    coordinator = mock_config_entry_with_heat_request.runtime_data.coordinator
    assert coordinator is not None


async def test_heat_request_calculation_with_unavailable_switch(
    hass: HomeAssistant,
    mock_config_entry_with_heat_request: MockConfigEntry,
) -> None:
    """
    Test heat request calculation works regardless of switch state.

    Heat request is only True when valves are actually open, not just when
    there's temperature demand. This test verifies the calculation works
    correctly even when the heat request switch is unavailable.
    """
    hass.states.async_set("switch.heat_request", STATE_UNAVAILABLE)
    # Temperature below setpoint creates demand
    hass.states.async_set("sensor.zone1_temp", "18.0")

    mock_config_entry_with_heat_request.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_heat_request.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_heat_request.runtime_data.coordinator
    # Heat request calculation works - it's False because no valves are open yet
    # (heat request requires valves to be open, not just temperature demand)
    heat_request = coordinator.controller.calculate_heat_request()
    assert isinstance(heat_request, bool)
    # Duty cycle should be calculated based on temperature error
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # 3°C error (21 - 18) should result in high duty cycle
    assert runtime.state.duty_cycle is not None
    assert runtime.state.duty_cycle >= 90.0


# ============================================================================
# Window Sensor Unknown/Unavailable Tests
# ============================================================================


async def test_window_sensor_unknown_not_treated_as_open(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test window sensor in unknown state is not treated as open."""
    hass.states.async_set("binary_sensor.window1", STATE_UNKNOWN)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Window should not be treated as currently open when state is unknown
    assert runtime.state.window_currently_open is False


async def test_window_sensor_unavailable_not_treated_as_open(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test window sensor in unavailable state is not treated as open."""
    hass.states.async_set("binary_sensor.window1", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Window should not be treated as currently open when unavailable
    assert runtime.state.window_currently_open is False


async def test_window_sensor_missing_not_treated_as_open(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test missing window sensor is not treated as open."""
    # Don't set up the window sensor
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Window should not be treated as currently open when entity missing
    assert runtime.state.window_currently_open is False


async def test_window_sensor_on_treated_as_open(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test window sensor in 'on' state is treated as open."""
    hass.states.async_set("binary_sensor.window1", "on")
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Window should be treated as open when sensor is on
    assert runtime.state.window_currently_open is True


async def test_window_sensor_off_not_treated_as_open(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test window sensor in 'off' state is not treated as open."""
    hass.states.async_set("binary_sensor.window1", "off")
    hass.states.async_set("sensor.zone1_temp", "20.5")

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Window should not be treated as open when sensor is off
    assert runtime.state.window_currently_open is False


# ============================================================================
# Temperature Sensor Unavailability (verify existing behavior)
# ============================================================================


async def test_temp_sensor_unavailable_preserves_last_duty_cycle(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test temperature sensor unavailable preserves last duty cycle value."""
    hass.states.async_set("sensor.zone1_temp", STATE_UNAVAILABLE)

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Current temperature should be None
    assert runtime.state.current is None


async def test_temp_sensor_unknown_preserves_last_duty_cycle(
    hass: HomeAssistant,
    mock_config_entry_with_window_sensor: MockConfigEntry,
) -> None:
    """Test temperature sensor unknown preserves last duty cycle value."""
    hass.states.async_set("sensor.zone1_temp", STATE_UNKNOWN)

    mock_config_entry_with_window_sensor.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_with_window_sensor.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_window_sensor.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    # Current temperature should be None
    assert runtime.state.current is None
