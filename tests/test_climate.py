"""Tests for UFH Controller climate platform."""

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def climate_entity_id() -> str:
    """Return the climate entity ID."""
    # Entity ID is device name + entity name ("Climate")
    return "climate.test_zone_1_climate"


async def test_climate_entity_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test climate entity is created on setup."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None


async def test_climate_default_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test climate entity has correct default state."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.state == HVACMode.HEAT


async def test_climate_hvac_modes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test climate entity reports correct HVAC modes."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    hvac_modes = state.attributes.get("hvac_modes")
    assert hvac_modes is not None
    assert HVACMode.HEAT in hvac_modes
    assert HVACMode.OFF in hvac_modes


async def test_climate_set_hvac_mode_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test setting HVAC mode to OFF."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.state == HVACMode.OFF
    assert state.attributes.get(ATTR_HVAC_ACTION) == HVACAction.OFF


async def test_climate_set_hvac_mode_heat(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test setting HVAC mode back to HEAT."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # First set to OFF
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )

    # Then back to HEAT
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.state == HVACMode.HEAT


async def test_climate_set_temperature(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test setting target temperature."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_TEMPERATURE: 23.0},
        blocking=True,
    )

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get("temperature") == 23.0


async def test_climate_temperature_limits(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test temperature limits are respected."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get("min_temp") == 16.0
    assert state.attributes.get("max_temp") == 28.0
    assert state.attributes.get("target_temp_step") == 0.5


async def test_climate_preset_modes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test preset modes are available."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    preset_modes = state.attributes.get("preset_modes")
    assert preset_modes is not None
    assert "comfort" in preset_modes
    assert "eco" in preset_modes
    assert "away" in preset_modes
    assert "boost" in preset_modes


async def test_climate_set_preset_comfort(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test setting comfort preset."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "comfort"},
        blocking=True,
    )

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get("preset_mode") == "comfort"
    assert state.attributes.get("temperature") == 22.0


async def test_climate_set_preset_eco(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test setting eco preset."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "eco"},
        blocking=True,
    )

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get("preset_mode") == "eco"
    assert state.attributes.get("temperature") == 19.0


async def test_climate_extra_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test extra state attributes are present."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    attrs = state.attributes

    # Check extra attributes are present
    assert "duty_cycle" in attrs
    assert "pid_error" in attrs
    assert "integral" in attrs
    assert "window_blocked" in attrs
    assert "is_requesting_heat" in attrs


async def test_climate_hvac_action_idle(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test HVAC action is IDLE when enabled but valve off."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    # Default state: enabled (HEAT mode) but valve_on=False
    assert state.state == HVACMode.HEAT
    assert state.attributes.get(ATTR_HVAC_ACTION) == HVACAction.IDLE


async def test_climate_no_zones(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test no climate entities created when no zones configured."""
    mock_config_entry_no_zones.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()

    # No climate entities should be created
    states = hass.states.async_entity_ids(CLIMATE_DOMAIN)
    assert len(states) == 0
