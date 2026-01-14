"""Tests for EMA (Exponential Moving Average) temperature filtering behavior."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
)


async def test_ema_filter_smooths_temperature_spikes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that EMA filter smooths out sudden temperature spikes."""
    # Start with a stable temperature
    hass.states.async_set("sensor.zone1_temp", "20.0")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # First update establishes baseline
    await coordinator.async_refresh()
    initial_temp = runtime.state.current
    assert initial_temp is not None
    assert initial_temp == pytest.approx(20.0)  # First reading, no previous to filter

    # Now simulate a sudden spike
    hass.states.async_set("sensor.zone1_temp", "25.0")  # 5 degree spike
    await coordinator.async_refresh()

    # The filtered temperature should NOT jump to 25.0
    # With tau=600s and dt=60s, alpha=0.0909
    # Expected: 0.0909 * 25 + 0.9091 * 20 = 2.27 + 18.18 = 20.45
    filtered_temp = runtime.state.current
    assert filtered_temp is not None
    assert filtered_temp < 21.0  # Should be much less than the spike
    assert filtered_temp > 20.0  # But more than the previous value


async def test_ema_filter_disabled_when_tau_zero(
    hass: HomeAssistant,
) -> None:
    """Test that EMA filter is disabled when time constant is 0."""
    zone_data = {
        "id": "zone1",
        "name": "Test Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "temp_ema_time_constant": 0,  # Disable EMA filtering
        "window_sensors": [],
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller_no_ema",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_no_ema",
        unique_id="test_controller_no_ema",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1_no_ema",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )

    hass.states.async_set("sensor.zone1_temp", "20.0")

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # First update
    await coordinator.async_refresh()
    assert runtime.state.current == pytest.approx(20.0)

    # Now simulate a sudden change - with tau=0, no filtering should occur
    hass.states.async_set("sensor.zone1_temp", "25.0")
    await coordinator.async_refresh()

    # With tau=0, the temperature should immediately jump to the raw value
    assert runtime.state.current == pytest.approx(25.0)

    # Cleanup
    await hass.config_entries.async_unload(config_entry.entry_id)
