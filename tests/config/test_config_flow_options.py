"""Tests for Underfloor Heating Controller options flow."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
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
    assert "heat_accounting" in result["menu_options"]


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


async def test_options_flow_heat_accounting_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test navigating to heat accounting form from menu."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Select heat_accounting from menu
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "heat_accounting"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "heat_accounting"


async def test_options_flow_update_supply_temperature(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating supply temperature entity via options flow."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Navigate to heat_accounting
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "heat_accounting"},
    )

    # Update supply temperature entity
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "supply_temp_entity": "sensor.supply_temp",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify the config entry data was updated
    assert mock_config_entry.data["supply_temp_entity"] == "sensor.supply_temp"


async def test_options_flow_update_supply_target_temp(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating supply_target_temp via options flow."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Navigate to heat_accounting
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "heat_accounting"},
    )

    # Update with supply_target_temp
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "supply_temp_entity": "sensor.supply_temp",
            "supply_target_temp": 45.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify the config entry data was updated
    assert mock_config_entry.data["supply_target_temp"] == 45.0


async def test_options_flow_update_heating_curve(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating heating curve parameters via options flow."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Navigate to heat_accounting
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "heat_accounting"},
    )

    # Update with heating curve parameters
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "supply_temp_entity": "sensor.supply_temp",
            "supply_target_temp": 40.0,
            "outdoor_temp_entity": "sensor.outdoor_temp",
            "outdoor_temp_warm": 20.0,
            "outdoor_temp_cold": -15.0,
            "supply_temp_warm": 30.0,
            "supply_temp_cold": 50.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify all heating curve parameters were saved
    assert mock_config_entry.data["outdoor_temp_entity"] == "sensor.outdoor_temp"
    assert mock_config_entry.data["outdoor_temp_warm"] == 20.0
    assert mock_config_entry.data["outdoor_temp_cold"] == -15.0
    assert mock_config_entry.data["supply_temp_warm"] == 30.0
    assert mock_config_entry.data["supply_temp_cold"] == 50.0


async def test_options_flow_heating_curve_defaults(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test heating curve fields have correct defaults when not configured."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Navigate to heat_accounting
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "heat_accounting"},
    )

    # Submit without setting heating curve values (use defaults)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            # Only supply entity and target
            "supply_temp_entity": "sensor.supply_temp",
            "supply_target_temp": 40.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify defaults were applied for heating curve
    assert mock_config_entry.data.get("outdoor_temp_entity") is None
    assert mock_config_entry.data["outdoor_temp_warm"] == DEFAULT_OUTDOOR_TEMP_WARM
    assert mock_config_entry.data["outdoor_temp_cold"] == DEFAULT_OUTDOOR_TEMP_COLD
    assert mock_config_entry.data["supply_temp_warm"] == DEFAULT_SUPPLY_TEMP_WARM
    assert mock_config_entry.data["supply_temp_cold"] == DEFAULT_SUPPLY_TEMP_COLD


async def test_options_flow_backwards_compatible(
    hass: HomeAssistant,
) -> None:
    """Test existing config entries without heating curve work correctly."""
    # Create entry with only old-style heat accounting (no heating curve fields)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "controller_id": "test_backwards",
            "supply_temp_entity": "sensor.supply_temp",
            "supply_target_temp": 42.0,
            # No heating curve fields - simulates pre-heating-curve config
        },
        options={},
        subentries_data=[],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ufh_controller.async_setup_entry",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Navigate to heat_accounting
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "heat_accounting"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "heat_accounting"

    # The form should show with existing supply_target_temp and defaults for new fields
    # Submit to verify backwards compatibility
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "supply_temp_entity": "sensor.supply_temp",
            "supply_target_temp": 42.0,
            # Heating curve fields will use defaults
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Original field preserved, new fields get defaults
    assert entry.data["supply_target_temp"] == 42.0
    assert entry.data["outdoor_temp_warm"] == DEFAULT_OUTDOOR_TEMP_WARM
    assert entry.data["outdoor_temp_cold"] == DEFAULT_OUTDOOR_TEMP_COLD
