"""Tests for Underfloor Heating Controller climate platform."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import SUBENTRY_TYPE_ZONE


@pytest.fixture
def climate_entity_id() -> str:
    """Return the climate entity ID."""
    # Entity ID is device name + entity name ("Thermostat")
    return "climate.test_zone_1_thermostat"


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


async def test_climate_available_during_initializing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test climate entity is available during initialization."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.state in (HVACMode.HEAT, HVACMode.OFF)


async def test_climate_default_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
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
    mock_temp_sensor: None,
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
    mock_temp_sensor: None,
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
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test setting HVAC mode requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # Set to OFF
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: climate_entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
            blocking=True,
        )

        # Verify refresh was requested
        mock_refresh.assert_called()

        # Reset mock
        mock_refresh.reset_mock()

        # Set back to HEAT
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: climate_entity_id, ATTR_HVAC_MODE: HVACMode.HEAT},
            blocking=True,
        )

        # Verify refresh was requested again
        mock_refresh.assert_called()


async def test_climate_set_temperature(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
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
    mock_temp_sensor: None,
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
    mock_temp_sensor: None,
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
    assert "home" in preset_modes
    assert "away" in preset_modes
    assert "eco" in preset_modes
    assert "comfort" in preset_modes
    assert "boost" in preset_modes


async def test_climate_set_preset_comfort(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test setting comfort preset requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "comfort"},
            blocking=True,
        )

        # Setpoint and preset_mode are applied together with a single refresh
        assert mock_refresh.call_count == 1

    zone_state = coordinator.controller.get_zone_runtime("zone1").state
    assert zone_state.setpoint == 22.0
    assert zone_state.preset_mode == "comfort"


async def test_climate_set_preset_eco(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test setting eco preset requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "eco"},
            blocking=True,
        )

        # Setpoint and preset_mode are applied together with a single refresh
        assert mock_refresh.call_count == 1

    zone_state = coordinator.controller.get_zone_runtime("zone1").state
    assert zone_state.setpoint == 19.0
    assert zone_state.preset_mode == "eco"


async def test_climate_extra_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
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
    assert "pid_proportional" in attrs
    assert "pid_integral" in attrs
    assert "pid_derivative" in attrs
    assert "window" in attrs
    assert "heat" in attrs
    assert "zone_status" in attrs
    assert attrs["zone_status"] == "normal"


async def test_climate_hvac_action_idle(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    climate_entity_id: str,
) -> None:
    """Test HVAC action is IDLE when enabled but valve off."""
    # Set temperature above default setpoint so no heating is requested
    hass.states.async_set("sensor.zone1_temp", "25.0")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    # Temperature above setpoint: enabled (HEAT mode) but valve_state=ValveState.OFF
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


async def test_climate_restore_setpoint_from_store(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test climate entity restores setpoint from Store API (not RestoreEntity)."""
    # Store API should be authoritative for setpoint, not RestoreEntity
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "integral": 0.0,
                "last_error": 0.0,
                "setpoint": 23.5,
                "enabled": True,
                "temperature": 20.0,
                "display_temp": 20.0,
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get(ATTR_TEMPERATURE) == 23.5


async def test_climate_restore_hvac_mode_off_from_store(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test climate entity restores HVAC mode OFF from Store API."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "integral": 0.0,
                "last_error": 0.0,
                "setpoint": 21.0,
                "enabled": False,
                "temperature": 20.0,
                "display_temp": 20.0,
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_restore_preset_mode_from_store(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test climate entity restores preset mode from Store API."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "integral": 0.0,
                "last_error": 0.0,
                "setpoint": 22.0,  # comfort preset temperature
                "enabled": True,
                "preset_mode": "comfort",
                "temperature": 20.0,
                "display_temp": 20.0,
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get(ATTR_PRESET_MODE) == "comfort"
    assert state.attributes.get(ATTR_TEMPERATURE) == 22.0


async def test_climate_preset_cleared_when_none_stored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test preset mode is None when no preset stored (manual temperature)."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "integral": 0.0,
                "last_error": 0.0,
                "setpoint": 23.5,  # manual temperature, not a preset
                "enabled": True,
                "temperature": 20.0,
                "display_temp": 20.0,
                # No preset_mode key - indicates manual temperature
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get(ATTR_PRESET_MODE) is None
    assert state.attributes.get(ATTR_TEMPERATURE) == 23.5


async def test_climate_config_change_applies_in_place(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test setpoint limits and presets update without recreating the entity."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "away"},
        blocking=True,
    )

    zone_subentry = next(
        subentry
        for subentry in mock_config_entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_ZONE
    )
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        hass.config_entries.async_update_subentry(
            mock_config_entry,
            zone_subentry,
            data={
                **zone_subentry.data,
                "setpoint": {"min": 10.0, "max": 30.0, "step": 0.1, "default": 21.0},
                "presets": {"home": 19.3, "eco": 18.0},
            },
        )
        await hass.async_block_till_done()
        mock_reload.assert_not_called()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get("min_temp") == 10.0
    assert state.attributes.get("max_temp") == 30.0
    assert state.attributes.get("target_temp_step") == 0.1
    assert state.attributes.get("preset_modes") == ["home", "eco"]
    # The active preset was removed from config, so it is cleared
    assert state.attributes.get(ATTR_PRESET_MODE) is None

    entry = er.async_get(hass).async_get(climate_entity_id)
    assert entry is not None
    assert entry.capabilities is not None
    assert entry.capabilities["target_temp_step"] == 0.1

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "home"},
        blocking=True,
    )
    coordinator = mock_config_entry.runtime_data.coordinator
    zone_state = coordinator.controller.get_zone_runtime("zone1").state
    assert zone_state.setpoint == 19.3
    assert zone_state.preset_mode == "home"


async def test_climate_presets_removed_in_place(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
    climate_entity_id: str,
) -> None:
    """Test removing all presets drops the preset feature in place."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    zone_subentry = next(
        subentry
        for subentry in mock_config_entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_ZONE
    )
    hass.config_entries.async_update_subentry(
        mock_config_entry,
        zone_subentry,
        data={**zone_subentry.data, "presets": {}},
    )
    await hass.async_block_till_done()

    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes.get("preset_modes") is None
    assert not (
        state.attributes["supported_features"] & ClimateEntityFeature.PRESET_MODE
    )
