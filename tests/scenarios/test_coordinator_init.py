"""Tests for coordinator initialization deferral via pending entities."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    INITIALIZING_TIMEOUT,
    INITIALIZING_UPDATE_INTERVAL,
    ControllerStatus,
)


class TestPendingEntitiesSetup:
    """Test pending entities are populated during listener setup."""

    async def test_pending_entities_populated_on_first_refresh(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Pending entities set contains all listened entity IDs after setup."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # mock_config_entry has dhw_active_entity + zone1 valve_switch
        assert "binary_sensor.dhw_active" in coordinator._entities_pending
        assert "switch.zone1_valve" in coordinator._entities_pending

    async def test_pending_entities_includes_all_controller_entities(
        self,
        hass: HomeAssistant,
        mock_config_entry_all_entities: MockConfigEntry,
    ) -> None:
        """All configured controller-level entities are tracked as pending."""
        mock_config_entry_all_entities.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
        await hass.async_block_till_done()

        pending = (
            mock_config_entry_all_entities.runtime_data.coordinator._entities_pending
        )
        assert pending >= {
            "switch.heat_request",
            "select.summer_mode",
            "binary_sensor.dhw_active",
            "switch.zone1_valve",
        }


class TestPendingEntitiesPruning:
    """Test pending entities are removed when they report valid state."""

    async def test_valid_state_removes_from_pending_via_listener(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Entity is removed from pending set when listener receives valid state."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert "switch.zone1_valve" in coordinator._entities_pending

        hass.states.async_set("switch.zone1_valve", "off")
        await hass.async_block_till_done()

        assert "switch.zone1_valve" not in coordinator._entities_pending

    @pytest.mark.parametrize("state", ["unavailable", "unknown"])
    async def test_invalid_state_keeps_entity_pending(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        state: str,
    ) -> None:
        """Entity stays pending when listener receives unavailable/unknown."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert "switch.zone1_valve" in coordinator._entities_pending

        hass.states.async_set("switch.zone1_valve", state)
        await hass.async_block_till_done()

        assert "switch.zone1_valve" in coordinator._entities_pending

    async def test_valid_states_pruned_during_update(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Entities with valid state are pruned during update loop."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Pending set is populated after first refresh; next cycle prunes them
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator._entities_pending


class TestInitializationDeferral:
    """Test controller stays INITIALIZING until pending entities are resolved."""

    async def test_stays_initializing_while_entities_pending(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller remains INITIALIZING with fast update interval."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        assert coordinator._entities_pending
        assert coordinator.status == ControllerStatus.INITIALIZING
        assert coordinator.update_interval == timedelta(
            seconds=INITIALIZING_UPDATE_INTERVAL
        )

    async def test_transitions_when_all_entities_report(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller transitions to NORMAL with normal update interval."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Pending set populated after first refresh; next refresh prunes
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator._entities_pending
        assert coordinator.status == ControllerStatus.NORMAL
        assert coordinator.update_interval == timedelta(
            seconds=coordinator._controller.config.timing.controller_loop_interval
        )

    async def test_transitions_after_late_entity_report(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller transitions after pending entities come online."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.INITIALIZING

        # Entities come online
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")
        await hass.async_block_till_done()

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator._entities_pending
        assert coordinator.status == ControllerStatus.NORMAL


class TestInitializationTimeout:
    """Test pending entities timeout allows initialization to proceed."""

    async def test_timeout_allows_transition(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """After timeout, controller proceeds past INITIALIZING."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        # Valve not set → zone stays INITIALIZING → controller INITIALIZING

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.INITIALIZING

        # Valve comes online so zone can go NORMAL after timeout
        hass.states.async_set("switch.zone1_valve", "off")
        await hass.async_block_till_done()

        coordinator._controller.state.started_at = datetime.now(UTC) - timedelta(
            seconds=INITIALIZING_TIMEOUT + 1
        )

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.status == ControllerStatus.NORMAL

    async def test_no_timeout_before_deadline(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller stays INITIALIZING before timeout deadline."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "unavailable")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.status == ControllerStatus.INITIALIZING

    async def test_zone_evaluation_skipped_while_initializing(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Zone evaluation is skipped while controller is INITIALIZING."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")

        hass.services.async_register("switch", "turn_on", AsyncMock())
        hass.services.async_register("switch", "turn_off", AsyncMock())

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.INITIALIZING
        assert coordinator._controller.state.heat_request is None
