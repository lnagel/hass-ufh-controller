"""
Tests for coordinator external state change tracking.

This test suite verifies that the coordinator properly tracks expected states
for entities it controls and triggers refreshes when external changes occur.
"""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_external_dhw_state_change_triggers_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that external DHW entity state change triggers coordinator refresh.

    DHW is a read-only entity - any state change should trigger a refresh.
    """
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set initial DHW state
    hass.states.async_set("binary_sensor.dhw_active", "off")
    await hass.async_block_till_done()

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # External change to DHW state
        hass.states.async_set("binary_sensor.dhw_active", "on")
        await hass.async_block_till_done()

        # Should trigger refresh since DHW is a read-only entity
        mock_refresh.assert_called_once()


async def test_self_initiated_heat_request_change_no_extra_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """
    Test that self-initiated heat_request changes don't trigger extra refresh.

    When we set the expected state before calling the service, and the actual
    state matches our expectation, we should NOT trigger an additional refresh.
    """
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    # Set up heat_request entity initial state
    hass.states.async_set("switch.heat_request", "off")
    await hass.async_block_till_done()

    # Simulate the coordinator setting expected state and calling service
    # (mimics what _call_switch_service does)
    coordinator._expected_states["switch.heat_request"] = "on"

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # State change that matches our expectation (self-initiated)
        hass.states.async_set("switch.heat_request", "on")
        await hass.async_block_till_done()

        # Should NOT trigger refresh since this was our own change
        mock_refresh.assert_not_called()

        # Verify expected state was cleared
        assert coordinator._expected_states.get("switch.heat_request") is None


async def test_external_heat_request_change_triggers_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """
    Test that external heat_request changes trigger coordinator refresh.

    When the state changes to something other than what we expected (or we had
    no expectation), it's an external change and should trigger a refresh.
    """
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    # Set up heat_request entity initial state
    hass.states.async_set("switch.heat_request", "off")
    await hass.async_block_till_done()

    # No expected state set (simulates external change)
    coordinator._expected_states["switch.heat_request"] = None

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # External change to heat_request
        hass.states.async_set("switch.heat_request", "on")
        await hass.async_block_till_done()

        # Should trigger refresh since this was an external change
        mock_refresh.assert_called_once()


async def test_external_summer_mode_change_triggers_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """Test that external summer_mode changes trigger coordinator refresh."""
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    # Set up summer_mode entity initial state
    hass.states.async_set("select.summer_mode", "winter")
    await hass.async_block_till_done()

    # No expected state set (simulates external change)
    coordinator._expected_states["select.summer_mode"] = None

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # External change to summer_mode
        hass.states.async_set("select.summer_mode", "summer")
        await hass.async_block_till_done()

        # Should trigger refresh since this was an external change
        mock_refresh.assert_called_once()


async def test_entity_removed_no_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """Test that entity removal (new_state=None) does not trigger refresh."""
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    # Set up heat_request entity
    hass.states.async_set("switch.heat_request", "off")
    await hass.async_block_till_done()

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # Remove the entity (sets state to None internally)
        hass.states.async_remove("switch.heat_request")
        await hass.async_block_till_done()

        # Should NOT trigger refresh since entity was removed
        mock_refresh.assert_not_called()


async def test_external_circulation_state_change_triggers_refresh(
    hass: HomeAssistant,
    mock_config_entry_all_entities: MockConfigEntry,
) -> None:
    """
    Test that external circulation entity state change triggers refresh.

    Circulation is a read-only entity - any state change should trigger a refresh.
    """
    mock_config_entry_all_entities.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_all_entities.runtime_data.coordinator

    # Set initial circulation state
    hass.states.async_set("binary_sensor.circulation", "off")
    await hass.async_block_till_done()

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # External change to circulation state
        hass.states.async_set("binary_sensor.circulation", "on")
        await hass.async_block_till_done()

        # Should trigger refresh since circulation is a read-only entity
        mock_refresh.assert_called_once()


async def test_external_zone_valve_change_triggers_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that external zone valve state change triggers coordinator refresh.

    When someone manually toggles a zone valve switch, the coordinator should
    detect this as an external change and request a refresh.
    """
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set initial valve state
    hass.states.async_set("switch.zone1_valve", "off")
    await hass.async_block_till_done()

    # No expected state set (simulates external change)
    coordinator._expected_states["switch.zone1_valve"] = None

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # External change to valve state (someone manually turned it on)
        hass.states.async_set("switch.zone1_valve", "on")
        await hass.async_block_till_done()

        # Should trigger refresh since this was an external change
        mock_refresh.assert_called_once()


async def test_self_initiated_zone_valve_change_no_extra_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that self-initiated zone valve changes don't trigger extra refresh.

    When the coordinator turns a valve on/off, it sets the expected state first.
    The subsequent state change event should be recognized as our own change
    and not trigger an additional refresh.
    """
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set initial valve state
    hass.states.async_set("switch.zone1_valve", "off")
    await hass.async_block_till_done()

    # Simulate the coordinator setting expected state before calling service
    # (mimics what _call_switch_service does)
    coordinator._expected_states["switch.zone1_valve"] = "on"

    # Monitor refresh calls
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        # State change that matches our expectation (self-initiated)
        hass.states.async_set("switch.zone1_valve", "on")
        await hass.async_block_till_done()

        # Should NOT trigger refresh since this was our own change
        mock_refresh.assert_not_called()

        # Verify expected state was cleared
        assert coordinator._expected_states.get("switch.zone1_valve") is None
