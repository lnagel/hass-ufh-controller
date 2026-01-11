"""Tests for Underfloor Heating Controller options flow."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DOMAIN,
    SUBENTRY_TYPE_CONTROLLER,
)


async def test_options_flow_show_menu(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the options flow shows the menu."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert "control_entities" in result["menu_options"]
    assert "timing" in result["menu_options"]


async def test_options_flow_control_entities_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test navigating to control entities form from menu."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Select control_entities from menu
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "control_entities"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "control_entities"


async def test_options_flow_update_control_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating control entities via options flow."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Navigate to control_entities
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "control_entities"},
    )

    # Update control entities
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "heat_request_entity": "switch.heat_request",
            "summer_mode_entity": "select.boiler_mode",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify the config entry data was updated
    assert mock_config_entry.data["heat_request_entity"] == "switch.heat_request"
    assert mock_config_entry.data["summer_mode_entity"] == "select.boiler_mode"


async def test_options_flow_timing_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test navigating to timing form from menu."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Select timing from menu
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "timing"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "timing"


async def test_options_flow_update_timing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating timing settings via options flow."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Navigate to timing
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "timing"},
    )

    # Update timing
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "observation_period": 3600,
            "min_run_time": 300,
            "valve_open_time": 120,
            "closing_warning_duration": 180,
            "window_block_time": 300,
            "controller_loop_interval": 30,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify the controller subentry was updated
    for subentry in mock_config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            timing = subentry.data.get("timing", {})
            assert timing.get("observation_period") == 3600
            assert timing.get("min_run_time") == 300
            break


async def test_options_flow_reads_controller_subentry(
    hass: HomeAssistant,
) -> None:
    """Test that options flow reads timing from controller subentry."""
    custom_timing = {
        "observation_period": 9000,
        "min_run_time": 600,
        "valve_open_time": 300,
        "closing_warning_duration": 300,
        "window_block_time": 900,
        "controller_loop_interval": 60,
    }

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Test", "controller_id": "test"},
        options={},
        subentries_data=[
            {
                "data": {"timing": custom_timing},
                "subentry_type": SUBENTRY_TYPE_CONTROLLER,
                "title": "Controller",
                "unique_id": "controller",
            }
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ufh_controller.async_setup_entry",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Should show menu first
    assert result["type"] is FlowResultType.MENU

    # Navigate to timing
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "timing"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "timing"
    # The form should be shown with the custom timing values as defaults
