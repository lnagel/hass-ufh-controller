"""
Tests for coordinator external state change tracking.

Verifies that the coordinator properly tracks expected states for entities it
controls and triggers refreshes when external changes occur.
"""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import SummerMode
from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)


@pytest.mark.parametrize(
    ("entity_id", "initial_state", "new_state"),
    [
        ("binary_sensor.dhw_active", "off", "on"),
        ("switch.heat_request", "off", "on"),
        ("select.summer_mode", "winter", "summer"),
        ("switch.zone1_valve", "off", "on"),
    ],
)
async def test_external_state_change_triggers_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
    entity_id: str,
    initial_state: str,
    new_state: str,
) -> None:
    """
    Test that external entity state changes trigger coordinator refresh.

    Any state change to a monitored entity that doesn't match a coordinator-set
    expectation should trigger a refresh to pick up the new state.
    """
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    hass.states.async_set(entity_id, initial_state)
    await hass.async_block_till_done()

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        hass.states.async_set(entity_id, new_state)
        await hass.async_block_till_done()

        mock_refresh.assert_called_once()


@pytest.mark.parametrize(
    ("entity_id", "expected_state"),
    [
        ("switch.heat_request", "on"),
        ("switch.zone1_valve", "on"),
    ],
)
async def test_self_initiated_change_no_extra_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
    entity_id: str,
    expected_state: str,
) -> None:
    """
    Test that self-initiated changes don't trigger extra refresh.

    When the coordinator sets an expected state before calling a service,
    the resulting state change event should be recognized as self-initiated.
    """
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()

    # Simulate coordinator setting expected state before service call
    coordinator._expected_states[entity_id] = expected_state

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        hass.states.async_set(entity_id, expected_state)
        await hass.async_block_till_done()

        mock_refresh.assert_not_called()
        assert coordinator._expected_states.get(entity_id) is None


async def test_entity_removed_no_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """Test that entity removal (new_state=None) does not trigger refresh."""
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    hass.states.async_set("switch.heat_request", "off")
    await hass.async_block_till_done()

    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        hass.states.async_remove("switch.heat_request")
        await hass.async_block_till_done()

        mock_refresh.assert_not_called()


async def test_fail_safe_sets_expected_state_for_summer_mode(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """
    Test that fail-safe actions set expected state for summer mode.

    During fail-safe, the coordinator resets summer mode to 'auto'. The expected
    state must be set so this self-initiated change isn't treated as external.
    """
    mock_config_entry_all_entities.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("switch.zone1_valve", "on")

    # Register services needed by fail-safe actions
    hass.services.async_register("switch", "turn_off", AsyncMock())
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("select", "select_option", AsyncMock())

    coordinator = UFHControllerDataUpdateCoordinator(
        hass, mock_config_entry_all_entities
    )
    await coordinator._execute_fail_safe_actions()

    assert coordinator._expected_states.get("select.summer_mode") == SummerMode.AUTO
