"""Test Underfloor Heating Controller setup and unload."""

from types import MappingProxyType
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
)
from custom_components.ufh_controller.core.pid import PIDState


async def test_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test successful setup of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data is not None
    assert mock_config_entry.runtime_data.coordinator is not None


async def test_setup_entry_no_zones(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test setup with no zones configured."""
    mock_config_entry_no_zones.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test successful unload of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_reload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reload of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Reload the entry
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_config_update_parameter_change_in_place(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test parameter change updates config in-place without entity recreation."""
    mock_config_entry.add_to_hass(hass)
    # Set up temperature sensor so refresh cycle can read it
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Setup entry
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set up zone with PID state
    zone_runtime = coordinator.controller.get_zone_runtime("zone1")
    zone_runtime.state.setpoint = 22.0
    zone_runtime.pid.set_state(
        PIDState(
            error=-1.5,
            p_term=15.0,
            i_term=10.0,
            d_term=5.0,
            duty_cycle=30.0,
        )
    )

    # Find zone subentry
    zone_subentry = None
    for subentry in mock_config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_ZONE:
            zone_subentry = subentry
            break
    assert zone_subentry is not None

    # Change PID parameters in zone subentry (parameter change, not structural)
    new_pid = {**DEFAULT_PID, "kp": 20.0}  # Change Kp parameter
    updated_data = {**zone_subentry.data, "pid": new_pid}

    # Patch async_reload to verify it's NOT called
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        # Update subentry data (simulates user changing config in UI)
        hass.config_entries.async_update_subentry(
            mock_config_entry,
            zone_subentry,
            data=updated_data,
        )
        await hass.async_block_till_done()

        # Verify async_reload was NOT called (in-place update used instead)
        mock_reload.assert_not_called()

    # Verify runtime state was preserved and new PID parameters are applied
    zone_runtime_after = coordinator.controller.get_zone_runtime("zone1")
    assert zone_runtime_after.state.setpoint == 22.0
    # Temperature will be read from sensor during refresh
    assert zone_runtime_after.state.current is not None
    assert zone_runtime_after.pid.state is not None

    # Verify new PID parameters are applied
    assert zone_runtime_after.config.kp == 20.0

    # Note: duty_cycle will be recalculated with new kp during refresh
    # This is expected - the config update preserves state during rebuild,
    # but the refresh recalculates PID output with new parameters


async def test_config_update_structural_change_full_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test structural change (zone added) triggers full reload."""
    mock_config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "20.5")

    # Setup entry
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Patch async_reload to verify it IS called for structural changes
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload",
        new_callable=AsyncMock,
    ) as mock_reload:
        # Add a new zone (structural change)
        new_zone_data = {
            "id": "zone2",
            "name": "Test Zone 2",
            "circuit_type": "regular",
            "temp_sensor": "sensor.zone2_temp",
            "valve_switch": "switch.zone2_valve",
            "setpoint": DEFAULT_PID,
            "pid": DEFAULT_PID,
            "window_sensors": [],
        }
        new_subentry = ConfigSubentry(
            data=MappingProxyType(new_zone_data),
            subentry_type=SUBENTRY_TYPE_ZONE,
            title="Test Zone 2",
            unique_id="zone2",
        )

        hass.config_entries.async_add_subentry(mock_config_entry, new_subentry)
        await hass.async_block_till_done()

        # Verify async_reload WAS called (full reload for structural change)
        mock_reload.assert_called_once_with(mock_config_entry.entry_id)


async def test_config_update_controller_params_in_place(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test controller parameter change (timing) updates in-place."""
    mock_config_entry.add_to_hass(hass)

    # Setup entry (this creates controller subentry)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Find controller subentry (created during setup)
    controller_subentry = None
    for subentry in mock_config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            controller_subentry = subentry
            break
    assert controller_subentry is not None

    # Change timing parameter
    new_timing = {
        **controller_subentry.data["timing"],
        "controller_loop_interval": 45,  # Change from 30 to 45
    }
    updated_data = {**controller_subentry.data, "timing": new_timing}

    # Patch async_reload to verify it's NOT called
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        # Update controller subentry
        hass.config_entries.async_update_subentry(
            mock_config_entry,
            controller_subentry,
            data=updated_data,
        )
        await hass.async_block_till_done()

        # Verify async_reload was NOT called (in-place update)
        mock_reload.assert_not_called()

    # Verify new timing parameter is applied
    assert coordinator.controller.config.timing.controller_loop_interval == 45
