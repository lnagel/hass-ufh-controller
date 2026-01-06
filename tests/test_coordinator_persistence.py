"""Tests for UFH Controller coordinator persistence."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_coordinator_saves_state_on_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator saves state when entry is unloaded."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Mock the save method
    with patch.object(
        coordinator, "async_save_state", new_callable=AsyncMock
    ) as mock_save:
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        mock_save.assert_called_once()


async def test_coordinator_loads_stored_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator loads stored state on first update."""
    stored_data = {
        "version": 1,
        "controller_mode": "flush",
        "zones": {
            "zone1": {"integral": 45.5, "last_error": 0.5},
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Check mode was restored
    assert coordinator.controller.mode == "flush"

    # Check integral was restored
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.pid.state.integral == 45.5


async def test_coordinator_save_state_format(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator saves state in expected format."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set some state
    coordinator.controller.mode = "cycle"
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    runtime.pid.set_integral(75.0)
    runtime.pid.set_last_error(1.5)

    saved_data = None

    async def capture_save(data: dict) -> None:
        nonlocal saved_data
        saved_data = data

    with patch(
        "homeassistant.helpers.storage.Store.async_save", side_effect=capture_save
    ):
        await coordinator.async_save_state()

    assert saved_data is not None
    assert saved_data["version"] == 1
    assert saved_data["controller_mode"] == "cycle"
    assert "zones" in saved_data
    assert "zone1" in saved_data["zones"]
    assert saved_data["zones"]["zone1"]["integral"] == 75.0
    assert saved_data["zones"]["zone1"]["last_error"] == 1.5


async def test_coordinator_no_stored_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator handles no stored state gracefully."""
    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=None,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Should use default mode
    assert coordinator.controller.mode == "auto"

    # Integral should be 0
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.pid.state.integral == 0.0
