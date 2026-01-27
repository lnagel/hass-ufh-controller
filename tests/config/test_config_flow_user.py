"""Tests for Underfloor Heating Controller initial config flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ufh_controller.const import (
    DEFAULT_TIMING,
    DOMAIN,
)


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
            "summer_mode_entity": "select.summer_mode",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["heat_request_entity"] == "switch.boiler_heat"
    assert result["data"]["dhw_active_entity"] == "binary_sensor.dhw_active"
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
