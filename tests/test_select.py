"""Tests for Underfloor Heating Controller select platform."""

from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.components.select import (
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_OPTION
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import OperationMode


async def test_mode_select_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test mode select entity is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("select.test_controller_mode")
    assert state is not None
    assert state.state == OperationMode.AUTO


async def test_mode_select_options(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test mode select has correct options."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("select.test_controller_mode")
    assert state is not None
    options = state.attributes.get("options")
    assert options is not None
    for mode in OperationMode:
        assert mode.value in options


async def test_mode_select_change_to_flush(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test changing mode to flush."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "select.test_controller_mode"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: OperationMode.FLUSH},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == OperationMode.FLUSH

    coordinator = mock_config_entry.runtime_data.coordinator
    assert coordinator.controller.mode == OperationMode.FLUSH


async def test_mode_select_change_to_all_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test changing mode to all_off."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "select.test_controller_mode"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: OperationMode.ALL_OFF},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == OperationMode.ALL_OFF

    coordinator = mock_config_entry.runtime_data.coordinator
    assert coordinator.controller.mode == OperationMode.ALL_OFF
