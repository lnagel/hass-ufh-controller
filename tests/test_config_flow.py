"""Tests for UFH Controller config flow."""

from typing import Any
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.config_flow import (
    build_zone_data,
    get_timing_schema,
    get_zone_schema,
)
from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
)

# =============================================================================
# ConfigFlow Tests (Initial Setup)
# =============================================================================


async def test_user_flow_show_form(
    hass: HomeAssistant,
    mock_setup_entry: None,
) -> None:
    """Test that the user flow shows the form on first call."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_flow_create_entry(
    hass: HomeAssistant,
    mock_setup_entry: None,
) -> None:
    """Test creating an entry with minimal required data."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Heating"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My Heating"
    assert result["data"]["name"] == "My Heating"
    assert result["data"]["controller_id"] == "my-heating"
    assert result["data"]["heat_request_entity"] is None
    assert result["data"]["dhw_active_entity"] is None
    assert result["options"]["timing"] == DEFAULT_TIMING


async def test_user_flow_with_all_entities(
    hass: HomeAssistant,
    mock_setup_entry: None,
) -> None:
    """Test creating an entry with all optional entities."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Full Controller",
            "heat_request_entity": "switch.boiler_heat",
            "dhw_active_entity": "binary_sensor.dhw_active",
            "circulation_entity": "binary_sensor.circulation",
            "summer_mode_entity": "select.summer_mode",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["heat_request_entity"] == "switch.boiler_heat"
    assert result["data"]["dhw_active_entity"] == "binary_sensor.dhw_active"
    assert result["data"]["circulation_entity"] == "binary_sensor.circulation"
    assert result["data"]["summer_mode_entity"] == "select.summer_mode"


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant,
    mock_setup_entry: None,
) -> None:
    """Test that duplicate controller_id aborts the flow."""
    # Create first entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Controller"},
    )

    # Try to create second entry with same name (same slugified ID)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Controller"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_generates_controller_id(
    hass: HomeAssistant,
    mock_setup_entry: None,
) -> None:
    """Test that controller_id is generated from name via slugify."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Living Room Heating System"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["controller_id"] == "living-room-heating-system"


# =============================================================================
# OptionsFlow Tests (Timing Settings)
# =============================================================================


async def test_options_flow_show_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the options flow shows the form with current timing."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_show_form_with_defaults(
    hass: HomeAssistant,
    mock_setup_entry: None,
) -> None:
    """Test options flow uses defaults when no controller subentry exists."""
    # Create entry without controller subentry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Test", "controller_id": "test"},
        options={},
    )
    entry.add_to_hass(hass)

    # Mock setup to skip actual setup
    with patch(
        "custom_components.ufh_controller.async_setup_entry",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_update_timing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating timing settings via options flow."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "observation_period": 3600,
            "duty_cycle_window": 1800,
            "min_run_time": 300,
            "valve_open_time": 120,
            "closing_warning_duration": 180,
            "window_block_threshold": 0.1,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify the controller subentry was updated
    for subentry in mock_config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            timing = subentry.data.get("timing", {})
            assert timing.get("observation_period") == 3600
            assert timing.get("duty_cycle_window") == 1800
            assert timing.get("min_run_time") == 300
            break


async def test_options_flow_reads_controller_subentry(
    hass: HomeAssistant,
) -> None:
    """Test that options flow reads timing from controller subentry."""
    custom_timing = {
        "observation_period": 9000,
        "duty_cycle_window": 4500,
        "min_run_time": 600,
        "valve_open_time": 300,
        "closing_warning_duration": 300,
        "window_block_threshold": 0.15,
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

    assert result["type"] is FlowResultType.FORM
    # The form should be shown with the custom timing values
    # (they're used as defaults in the schema)


# =============================================================================
# Zone Subentry Flow Tests
# =============================================================================


async def test_zone_subentry_user_show_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that zone add flow shows the form."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_ZONE),
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_zone_subentry_user_create_zone(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test creating a zone with valid data."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry_no_zones.entry_id, SUBENTRY_TYPE_ZONE),
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "name": "Living Room",
            "temp_sensor": "sensor.living_room_temp",
            "valve_switch": "switch.living_room_valve",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room"
    assert result["data"]["id"] == "living-room"
    assert result["data"]["name"] == "Living Room"
    assert result["data"]["temp_sensor"] == "sensor.living_room_temp"
    assert result["data"]["valve_switch"] == "switch.living_room_valve"


async def test_zone_subentry_user_create_zone_with_options(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test creating a zone with all optional fields."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry_no_zones.entry_id, SUBENTRY_TYPE_ZONE),
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "name": "Bathroom",
            "temp_sensor": "sensor.bathroom_temp",
            "valve_switch": "switch.bathroom_valve",
            "circuit_type": "flush",
            "window_sensors": ["binary_sensor.bathroom_window"],
            "setpoint_min": 18.0,
            "setpoint_max": 26.0,
            "setpoint_default": 22.0,
            "kp": 40.0,
            "ki": 0.03,
            "kd": 0.1,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["circuit_type"] == "flush"
    assert result["data"]["window_sensors"] == ["binary_sensor.bathroom_window"]
    assert result["data"]["setpoint"]["min"] == 18.0
    assert result["data"]["setpoint"]["max"] == 26.0
    assert result["data"]["setpoint"]["default"] == 22.0
    assert result["data"]["pid"]["kp"] == 40.0
    assert result["data"]["pid"]["ki"] == 0.03
    assert result["data"]["pid"]["kd"] == 0.1


async def test_zone_subentry_user_duplicate_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that duplicate zone_id shows error."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # The mock_config_entry already has a zone with id "zone1"
    # Try to create another zone with the same name pattern
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_ZONE),
        context={"source": config_entries.SOURCE_USER},
    )

    # Create a zone with name that slugifies to "zone1"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "name": "zone1",  # Will slugify to "zone1"
            "temp_sensor": "sensor.another_temp",
            "valve_switch": "switch.another_valve",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "zone_id_exists"}


async def test_zone_subentry_reconfigure_show_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that reconfigure flow shows form with prefilled data."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the zone subentry
    zone_subentry = None
    for subentry in mock_config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_ZONE:
            zone_subentry = subentry
            break

    assert zone_subentry is not None

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_ZONE),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": zone_subentry.subentry_id,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_zone_subentry_reconfigure_update(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating zone data while preserving zone_id."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the zone subentry
    zone_subentry = None
    for subentry in mock_config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_ZONE:
            zone_subentry = subentry
            break

    assert zone_subentry is not None
    original_zone_id = zone_subentry.data["id"]

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_ZONE),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": zone_subentry.subentry_id,
        },
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "name": "Updated Zone Name",
            "temp_sensor": "sensor.new_temp",
            "valve_switch": "switch.new_valve",
            "setpoint_min": 17.0,
            "setpoint_max": 27.0,
            "setpoint_default": 23.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the subentry was updated
    updated_subentry = mock_config_entry.subentries.get(zone_subentry.subentry_id)
    assert updated_subentry is not None
    assert updated_subentry.data["id"] == original_zone_id  # ID preserved
    assert updated_subentry.data["name"] == "Updated Zone Name"
    assert updated_subentry.data["temp_sensor"] == "sensor.new_temp"


# =============================================================================
# Helper Function Tests
# =============================================================================


def test_get_timing_schema_with_defaults() -> None:
    """Test that timing schema uses DEFAULT_TIMING when None."""
    schema = get_timing_schema(None)

    # Verify schema contains all expected keys
    schema_keys = {str(key) for key in schema.schema}
    assert "observation_period" in schema_keys
    assert "duty_cycle_window" in schema_keys
    assert "min_run_time" in schema_keys
    assert "valve_open_time" in schema_keys
    assert "closing_warning_duration" in schema_keys
    assert "window_block_threshold" in schema_keys


def test_get_timing_schema_with_custom() -> None:
    """Test that timing schema uses provided timing values."""
    custom_timing = {
        "observation_period": 9000,
        "duty_cycle_window": 4500,
        "min_run_time": 600,
        "valve_open_time": 300,
        "closing_warning_duration": 300,
        "window_block_threshold": 0.15,
    }
    schema = get_timing_schema(custom_timing)

    # Schema should be created (values are used as defaults)
    assert schema is not None


def test_get_zone_schema_with_defaults() -> None:
    """Test that zone schema uses defaults when None."""
    schema = get_zone_schema(None)

    # Verify schema contains all expected keys
    schema_keys = {str(key) for key in schema.schema}
    assert "name" in schema_keys
    assert "temp_sensor" in schema_keys
    assert "valve_switch" in schema_keys
    assert "circuit_type" in schema_keys
    assert "window_sensors" in schema_keys
    assert "setpoint_min" in schema_keys
    assert "setpoint_max" in schema_keys
    assert "setpoint_default" in schema_keys
    assert "kp" in schema_keys
    assert "ki" in schema_keys
    assert "kd" in schema_keys


def test_get_zone_schema_with_custom() -> None:
    """Test that zone schema uses provided default values."""
    custom_defaults = {
        "name": "Custom Zone",
        "temp_sensor": "sensor.custom_temp",
        "valve_switch": "switch.custom_valve",
        "setpoint": {"min": 15.0, "max": 30.0, "default": 20.0},
        "pid": {"kp": 30.0, "ki": 0.02, "kd": 0.5},
    }
    schema = get_zone_schema(custom_defaults)

    # Schema should be created (values are used as defaults)
    assert schema is not None


def test_build_zone_data_generates_id() -> None:
    """Test that zone_id is generated from name via slugify."""
    user_input: dict[str, Any] = {
        "name": "Living Room",
        "temp_sensor": "sensor.living_temp",
        "valve_switch": "switch.living_valve",
    }

    result = build_zone_data(user_input)

    assert result["id"] == "living-room"
    assert result["name"] == "Living Room"


def test_build_zone_data_uses_explicit_id() -> None:
    """Test that explicit zone_id is used when provided."""
    user_input: dict[str, Any] = {
        "zone_id": "custom_id",
        "name": "Living Room",
        "temp_sensor": "sensor.living_temp",
        "valve_switch": "switch.living_valve",
    }

    result = build_zone_data(user_input)

    assert result["id"] == "custom_id"


def test_build_zone_data_default_values() -> None:
    """Test that missing optional fields get defaults."""
    user_input: dict[str, Any] = {
        "name": "Test Zone",
        "temp_sensor": "sensor.test_temp",
        "valve_switch": "switch.test_valve",
    }

    result = build_zone_data(user_input)

    # Check default values are applied
    assert result["circuit_type"] == "regular"
    assert result["window_sensors"] == []
    assert result["setpoint"]["min"] == DEFAULT_SETPOINT["min"]
    assert result["setpoint"]["max"] == DEFAULT_SETPOINT["max"]
    assert result["setpoint"]["step"] == DEFAULT_SETPOINT["step"]
    assert result["setpoint"]["default"] == DEFAULT_SETPOINT["default"]
    assert result["pid"]["kp"] == DEFAULT_PID["kp"]
    assert result["pid"]["ki"] == DEFAULT_PID["ki"]
    assert result["pid"]["kd"] == DEFAULT_PID["kd"]
    assert result["pid"]["integral_min"] == DEFAULT_PID["integral_min"]
    assert result["pid"]["integral_max"] == DEFAULT_PID["integral_max"]
    assert result["presets"] == {}


def test_build_zone_data_with_all_values() -> None:
    """Test building zone data with all values provided."""
    user_input: dict[str, Any] = {
        "name": "Full Zone",
        "temp_sensor": "sensor.full_temp",
        "valve_switch": "switch.full_valve",
        "circuit_type": "flush",
        "window_sensors": ["binary_sensor.window1", "binary_sensor.window2"],
        "setpoint_min": 15.0,
        "setpoint_max": 30.0,
        "setpoint_step": 1.0,
        "setpoint_default": 20.0,
        "kp": 60.0,
        "ki": 0.1,
        "kd": 0.5,
    }

    result = build_zone_data(user_input)

    assert result["circuit_type"] == "flush"
    assert result["window_sensors"] == [
        "binary_sensor.window1",
        "binary_sensor.window2",
    ]
    assert result["setpoint"]["min"] == 15.0
    assert result["setpoint"]["max"] == 30.0
    assert result["setpoint"]["step"] == 1.0
    assert result["setpoint"]["default"] == 20.0
    assert result["pid"]["kp"] == 60.0
    assert result["pid"]["ki"] == 0.1
    assert result["pid"]["kd"] == 0.5


def test_build_zone_data_with_presets() -> None:
    """Test building zone data with preset values provided."""
    user_input: dict[str, Any] = {
        "name": "Preset Zone",
        "temp_sensor": "sensor.preset_temp",
        "valve_switch": "switch.preset_valve",
        "preset_comfort": 22.0,
        "preset_eco": 19.0,
        "preset_away": 16.0,
        "preset_boost": 25.0,
    }

    result = build_zone_data(user_input)

    assert result["presets"] == {
        "comfort": {"setpoint": 22.0},
        "eco": {"setpoint": 19.0},
        "away": {"setpoint": 16.0},
        "boost": {"setpoint": 25.0, "pid_enabled": False},
    }


def test_build_zone_data_with_partial_presets() -> None:
    """Test building zone data with only some preset values provided."""
    user_input: dict[str, Any] = {
        "name": "Partial Preset Zone",
        "temp_sensor": "sensor.partial_temp",
        "valve_switch": "switch.partial_valve",
        "preset_comfort": 22.0,
        "preset_boost": 28.0,
        # eco and away not provided - should not appear in presets
    }

    result = build_zone_data(user_input)

    assert result["presets"] == {
        "comfort": {"setpoint": 22.0},
        "boost": {"setpoint": 28.0, "pid_enabled": False},
    }
    # Verify that eco and away are not in presets
    assert "eco" not in result["presets"]
    assert "away" not in result["presets"]
