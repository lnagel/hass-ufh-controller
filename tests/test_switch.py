"""Tests for UFH Controller switch platform."""

from typing import Any

import pytest
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
)

MOCK_ZONE_DATA: dict[str, Any] = {
    "id": "zone1",
    "name": "Test Zone 1",
    "circuit_type": "regular",
    "temp_sensor": "sensor.zone1_temp",
    "valve_switch": "switch.zone1_valve",
    "setpoint": DEFAULT_SETPOINT,
    "pid": DEFAULT_PID,
    "window_sensors": [],
}


@pytest.fixture
def mock_config_entry_no_dhw() -> MockConfigEntry:
    """Return a mock config entry without DHW entity configured."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller No DHW",
        data={
            "name": "Test Controller No DHW",
            "controller_id": "test_controller_no_dhw",
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_id_no_dhw",
        unique_id="test_controller_no_dhw",
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


async def test_flush_switch_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test flush enabled switch is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("switch.test_controller_flush_enabled")
    assert state is not None
    assert state.state == STATE_OFF


async def test_flush_switch_turn_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test turning on flush switch."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "switch.test_controller_flush_enabled"

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON

    coordinator = mock_config_entry.runtime_data.coordinator
    assert coordinator.controller.state.flush_enabled is True


async def test_flush_switch_turn_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test turning off flush switch."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "switch.test_controller_flush_enabled"

    # First turn on
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    # Then turn off
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    coordinator = mock_config_entry.runtime_data.coordinator
    assert coordinator.controller.state.flush_enabled is False


async def test_flush_switch_not_created_without_dhw(
    hass: HomeAssistant,
    mock_config_entry_no_dhw: MockConfigEntry,
) -> None:
    """Test flush switch is NOT created when DHW entity is not configured."""
    mock_config_entry_no_dhw.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_dhw.entry_id)
    await hass.async_block_till_done()

    # Flush switch should not exist without DHW entity
    state = hass.states.get("switch.test_controller_no_dhw_flush_enabled")
    assert state is None
