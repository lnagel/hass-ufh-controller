"""
Tests for coordinator update scenarios triggered by external entity changes.

This test suite verifies that the coordinator properly responds to state changes
from external entities (mode changes, setpoint adjustments, zone enable/disable,
flush enable/disable, etc.) by requesting a refresh cycle.
"""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import OperationMode


async def test_mode_change_triggers_coordinator_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that changing mode requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        await coordinator.set_mode(OperationMode.ALL_OFF)

        # Verify refresh was requested
        mock_refresh.assert_called_once()


async def test_setpoint_change_triggers_coordinator_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that changing setpoint requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        await coordinator.set_zone_setpoint("zone1", 22.0)

        # Verify refresh was requested
        mock_refresh.assert_called_once()


async def test_zone_enable_triggers_coordinator_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that enabling/disabling zone requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        await coordinator.set_zone_enabled("zone1", enabled=False)

        # Verify refresh was requested
        mock_refresh.assert_called_once()


async def test_flush_enabled_triggers_coordinator_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that enabling/disabling flush requests coordinator refresh."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        await coordinator.set_flush_enabled(enabled=True)

        # Verify refresh was requested
        mock_refresh.assert_called_once()
