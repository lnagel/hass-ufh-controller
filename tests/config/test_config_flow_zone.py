"""Tests for Underfloor Heating Controller zone subentry flow and helpers."""

from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.config_flow import (
    build_presets_from_input,
    build_zone_data,
    get_timing_schema,
    get_zone_entities_schema,
    get_zone_presets_schema,
    get_zone_schema,
    get_zone_temperature_schema,
)
from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_PRESETS,
    DEFAULT_SETPOINT,
    SUBENTRY_TYPE_ZONE,
    TimingDefaults,
)


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


async def test_zone_subentry_reconfigure_show_menu(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that reconfigure flow shows menu with configuration options."""
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

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "reconfigure"
    assert "zone_entities" in result["menu_options"]
    assert "temperature_control" in result["menu_options"]
    assert "presets" in result["menu_options"]


async def test_zone_subentry_zone_entities_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test navigating to zone entities form from menu."""
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

    # Select zone_entities from menu
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "zone_entities"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_entities"


async def test_zone_subentry_update_zone_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating zone entities while preserving other data."""
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

    # Navigate to zone_entities
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "zone_entities"},
    )

    # Update zone entities
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "name": "Updated Zone Name",
            "temp_sensor": "sensor.new_temp",
            "valve_switch": "switch.new_valve",
            "circuit_type": "flush",
            "window_sensors": ["binary_sensor.new_window"],
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
    assert updated_subentry.data["valve_switch"] == "switch.new_valve"
    assert updated_subentry.data["circuit_type"] == "flush"
    assert updated_subentry.data["window_sensors"] == ["binary_sensor.new_window"]


async def test_zone_subentry_temperature_control_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test navigating to temperature control form from menu."""
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

    # Select temperature_control from menu
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "temperature_control"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "temperature_control"


async def test_zone_subentry_update_temperature_control(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating temperature control settings."""
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

    # Navigate to temperature_control
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "temperature_control"},
    )

    # Update temperature control
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "setpoint_min": 17.0,
            "setpoint_max": 27.0,
            "setpoint_default": 23.0,
            "kp": 60.0,
            "ki": 0.002,
            "kd": 0.1,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the subentry was updated
    updated_subentry = mock_config_entry.subentries.get(zone_subentry.subentry_id)
    assert updated_subentry is not None
    assert updated_subentry.data["setpoint"]["min"] == 17.0
    assert updated_subentry.data["setpoint"]["max"] == 27.0
    assert updated_subentry.data["setpoint"]["default"] == 23.0
    assert updated_subentry.data["pid"]["kp"] == 60.0
    assert updated_subentry.data["pid"]["ki"] == 0.002
    assert updated_subentry.data["pid"]["kd"] == 0.1


async def test_zone_subentry_presets_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test navigating to presets form from menu."""
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

    # Select presets from menu
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "presets"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "presets"


async def test_zone_subentry_update_presets(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating zone presets."""
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

    # Navigate to presets
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "presets"},
    )

    # Update presets
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "preset_home": 20.0,
            "preset_away": 15.0,
            "preset_eco": 18.0,
            "preset_comfort": 23.0,
            "preset_boost": 26.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the subentry was updated
    updated_subentry = mock_config_entry.subentries.get(zone_subentry.subentry_id)
    assert updated_subentry is not None
    assert updated_subentry.data["presets"]["home"] == 20.0
    assert updated_subentry.data["presets"]["away"] == 15.0
    assert updated_subentry.data["presets"]["eco"] == 18.0
    assert updated_subentry.data["presets"]["comfort"] == 23.0
    assert updated_subentry.data["presets"]["boost"] == 26.0


async def test_zone_subentry_update_presets_partial(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating zone presets with only some presets set."""
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

    # Navigate to presets
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "presets"},
    )

    # Update presets with only comfort and eco set
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            "preset_comfort": 23.0,
            "preset_eco": 18.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the subentry was updated - only comfort and eco should be present
    updated_subentry = mock_config_entry.subentries.get(zone_subentry.subentry_id)
    assert updated_subentry is not None
    assert updated_subentry.data["presets"] == {"comfort": 23.0, "eco": 18.0}


# =============================================================================
# Helper Function Tests
# =============================================================================


def test_get_timing_schema_with_defaults() -> None:
    """Test that timing schema uses DEFAULT_TIMING when None."""
    schema = get_timing_schema(None)

    # Verify schema contains all expected keys
    schema_keys = {str(key) for key in schema.schema}
    assert "observation_period" in schema_keys
    assert "min_run_time" in schema_keys
    assert "valve_open_time" in schema_keys
    assert "closing_warning_duration" in schema_keys
    assert "window_block_time" in schema_keys


def test_get_timing_schema_with_custom() -> None:
    """Test that timing schema uses provided timing values."""
    custom_timing: TimingDefaults = {
        "observation_period": 9000,
        "min_run_time": 600,
        "valve_open_time": 300,
        "closing_warning_duration": 300,
        "window_block_time": 900,
        "controller_loop_interval": 60,
        "flush_duration": 600,
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
    assert result["presets"] == dict(DEFAULT_PRESETS)


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


def test_build_presets_from_input_all_values() -> None:
    """Test building presets with all values provided."""
    user_input: dict[str, Any] = {
        "preset_home": 21.0,
        "preset_away": 16.0,
        "preset_eco": 19.0,
        "preset_comfort": 22.0,
        "preset_boost": 25.0,
    }

    result = build_presets_from_input(user_input)

    assert result == {
        "home": 21.0,
        "away": 16.0,
        "eco": 19.0,
        "comfort": 22.0,
        "boost": 25.0,
    }


def test_build_presets_from_input_partial() -> None:
    """Test building presets with only some values provided."""
    user_input: dict[str, Any] = {
        "preset_comfort": 22.0,
        "preset_eco": 19.0,
    }

    result = build_presets_from_input(user_input)

    assert result == {"comfort": 22.0, "eco": 19.0}


def test_build_presets_from_input_empty() -> None:
    """Test building presets with no values provided."""
    user_input: dict[str, Any] = {}

    result = build_presets_from_input(user_input)

    assert result == {}


def test_build_presets_from_input_none_values() -> None:
    """Test that None values are filtered out."""
    user_input: dict[str, Any] = {
        "preset_comfort": 22.0,
        "preset_eco": None,
        "preset_away": 16.0,
        "preset_boost": None,
    }

    result = build_presets_from_input(user_input)

    assert result == {"comfort": 22.0, "away": 16.0}


def test_get_zone_entities_schema_with_defaults() -> None:
    """Test that zone entities schema uses defaults when None."""
    schema = get_zone_entities_schema(None)

    # Verify schema contains expected keys
    schema_keys = {str(key) for key in schema.schema}
    assert "name" in schema_keys
    assert "temp_sensor" in schema_keys
    assert "valve_switch" in schema_keys
    assert "circuit_type" in schema_keys
    assert "window_sensors" in schema_keys
    # Should NOT contain temperature/PID fields
    assert "setpoint_min" not in schema_keys
    assert "kp" not in schema_keys


def test_get_zone_entities_schema_with_custom() -> None:
    """Test that zone entities schema uses provided default values."""
    custom_defaults = {
        "name": "Custom Zone",
        "temp_sensor": "sensor.custom_temp",
        "valve_switch": "switch.custom_valve",
        "circuit_type": "flush",
        "window_sensors": ["binary_sensor.window"],
    }
    schema = get_zone_entities_schema(custom_defaults)

    # Schema should be created (values are used as defaults)
    assert schema is not None


def test_get_zone_temperature_schema_with_defaults() -> None:
    """Test that zone temperature schema uses defaults when None."""
    schema = get_zone_temperature_schema(None)

    # Verify schema contains expected keys
    schema_keys = {str(key) for key in schema.schema}
    assert "setpoint_min" in schema_keys
    assert "setpoint_max" in schema_keys
    assert "setpoint_default" in schema_keys
    assert "kp" in schema_keys
    assert "ki" in schema_keys
    assert "kd" in schema_keys
    # Should NOT contain entity fields
    assert "name" not in schema_keys
    assert "temp_sensor" not in schema_keys


def test_get_zone_temperature_schema_with_custom() -> None:
    """Test that zone temperature schema uses provided default values."""
    custom_defaults = {
        "setpoint": {"min": 15.0, "max": 30.0, "default": 20.0},
        "pid": {"kp": 30.0, "ki": 0.02, "kd": 0.5},
    }
    schema = get_zone_temperature_schema(custom_defaults)

    # Schema should be created (values are used as defaults)
    assert schema is not None


def test_get_zone_presets_schema_with_defaults() -> None:
    """Test that zone presets schema uses default presets when None."""
    schema = get_zone_presets_schema(None)

    # Verify schema contains expected keys
    schema_keys = {str(key) for key in schema.schema}
    assert "preset_home" in schema_keys
    assert "preset_away" in schema_keys
    assert "preset_eco" in schema_keys
    assert "preset_comfort" in schema_keys
    assert "preset_boost" in schema_keys


def test_get_zone_presets_schema_with_custom() -> None:
    """Test that zone presets schema uses provided preset values."""
    custom_defaults = {
        "presets": {
            "home": 20.0,
            "away": 15.0,
            "eco": 18.0,
            "comfort": 23.0,
            "boost": 26.0,
        }
    }
    schema = get_zone_presets_schema(custom_defaults)

    # Schema should be created (values are used as suggested values)
    assert schema is not None
