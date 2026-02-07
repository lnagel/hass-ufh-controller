"""Tests for coordinator initialization deferral via pending entities."""

import logging
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
        """Pending entities set contains all listened entity IDs after first refresh."""
        mock_config_entry.add_to_hass(hass)

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # mock_config_entry has dhw_active_entity + zone1 valve_switch
        assert "binary_sensor.dhw_active" in coordinator._pending_entities
        assert "switch.zone1_valve" in coordinator._pending_entities

    async def test_pending_entities_includes_all_controller_entities(
        self,
        hass: HomeAssistant,
        mock_config_entry_all_entities: MockConfigEntry,
    ) -> None:
        """All configured controller-level entities are tracked as pending."""
        mock_config_entry_all_entities.add_to_hass(hass)

        await hass.config_entries.async_setup(mock_config_entry_all_entities.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry_all_entities.runtime_data.coordinator

        assert "switch.heat_request" in coordinator._pending_entities
        assert "select.summer_mode" in coordinator._pending_entities
        assert "binary_sensor.dhw_active" in coordinator._pending_entities
        assert "switch.zone1_valve" in coordinator._pending_entities


class TestPendingEntitiesPruning:
    """Test pending entities are removed when they report valid state."""

    async def test_entity_removed_from_pending_via_state_change_listener(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Entity is removed from pending set when listener receives valid state."""
        mock_config_entry.add_to_hass(hass)

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert "switch.zone1_valve" in coordinator._pending_entities

        # Set a valid state - triggers listener
        hass.states.async_set("switch.zone1_valve", "off")
        await hass.async_block_till_done()

        assert "switch.zone1_valve" not in coordinator._pending_entities

    async def test_unavailable_state_does_not_remove_from_pending(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Entity stays in pending set when listener receives unavailable state."""
        mock_config_entry.add_to_hass(hass)

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert "switch.zone1_valve" in coordinator._pending_entities

        hass.states.async_set("switch.zone1_valve", "unavailable")
        await hass.async_block_till_done()

        assert "switch.zone1_valve" in coordinator._pending_entities

    async def test_unknown_state_does_not_remove_from_pending(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Entity stays in pending set when listener receives unknown state."""
        mock_config_entry.add_to_hass(hass)

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert "switch.zone1_valve" in coordinator._pending_entities

        hass.states.async_set("switch.zone1_valve", "unknown")
        await hass.async_block_till_done()

        assert "switch.zone1_valve" in coordinator._pending_entities

    async def test_pending_entities_pruned_during_update_without_listener(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Entities with valid state are pruned during update."""
        mock_config_entry.add_to_hass(hass)

        # Set valid states BEFORE setup so they exist before listener is created
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Pending set is populated after first refresh, so entities are still pending.
        # The next update cycle prunes entities that already have valid states.
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert "switch.zone1_valve" not in coordinator._pending_entities
        assert "binary_sensor.dhw_active" not in coordinator._pending_entities


class TestInitializationDeferral:
    """Test controller stays INITIALIZING until pending entities are resolved."""

    async def test_controller_stays_initializing_while_entities_pending(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller remains INITIALIZING while entities are pending."""
        mock_config_entry.add_to_hass(hass)
        # Temp sensor valid but valve and dhw NOT set -> pending
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        assert coordinator._pending_entities
        assert coordinator.status == ControllerStatus.INITIALIZING

    async def test_controller_transitions_when_all_entities_report(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller transitions when all entities report valid state."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Pending set populated after first refresh; next refresh prunes valid entities
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator._pending_entities
        assert coordinator.status == ControllerStatus.NORMAL

    async def test_controller_transitions_after_late_entity_report(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Controller transitions after initially-pending entity reports valid state."""
        mock_config_entry.add_to_hass(hass)
        # Start with temp valid but valve/dhw missing
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.INITIALIZING

        # Now entities come online
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")
        await hass.async_block_till_done()

        # Trigger a refresh so the status update runs
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator._pending_entities
        assert coordinator.status == ControllerStatus.NORMAL

    async def test_update_interval_changes_after_init_completes(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Update interval switches from fast to normal after initialization."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")
        hass.states.async_set("binary_sensor.dhw_active", "off")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        assert coordinator.status == ControllerStatus.NORMAL
        assert coordinator.update_interval == timedelta(
            seconds=coordinator._controller.config.timing.controller_loop_interval
        )

    async def test_fast_update_interval_during_init(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Update interval stays fast while INITIALIZING."""
        mock_config_entry.add_to_hass(hass)
        # Don't set valve/dhw so entities remain pending
        hass.states.async_set("sensor.zone1_temp", "20.5")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        assert coordinator.status == ControllerStatus.INITIALIZING
        assert coordinator.update_interval == timedelta(
            seconds=INITIALIZING_UPDATE_INTERVAL
        )


class TestInitializationTimeout:
    """Test pending entities timeout allows initialization to proceed."""

    async def test_timeout_allows_transition_despite_pending_entities(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """After INITIALIZING_TIMEOUT, controller proceeds despite pending entities."""
        mock_config_entry.add_to_hass(hass)
        # Temp and valve valid (so zone goes NORMAL), but dhw entity missing
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "off")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # dhw entity is not set → stays in pending → controller deferred
        assert "binary_sensor.dhw_active" in coordinator._pending_entities

        # Move started_at back past the timeout
        coordinator._started_at = datetime.now(UTC) - timedelta(
            seconds=INITIALIZING_TIMEOUT + 1
        )

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Timeout fires, zone is NORMAL → controller should be NORMAL
        assert coordinator.status == ControllerStatus.NORMAL

    async def test_timeout_logs_warning(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Timeout logs a warning with the pending entity IDs."""
        mock_config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.zone1_temp", "20.5")
        hass.states.async_set("switch.zone1_valve", "unavailable")

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Move started_at back past the timeout
        coordinator._started_at = datetime.now(UTC) - timedelta(
            seconds=INITIALIZING_TIMEOUT + 1
        )

        with caplog.at_level(logging.WARNING):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert any(
            "Timed out waiting for entities to report valid state" in record.message
            for record in caplog.records
        )

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

        # started_at is recent, so timeout should NOT fire
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
        # Don't set valve/dhw -> entities remain pending

        hass.services.async_register("switch", "turn_on", AsyncMock())
        hass.services.async_register("switch", "turn_off", AsyncMock())

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert coordinator.status == ControllerStatus.INITIALIZING

        # heat_request stays None during initialization (no evaluation)
        assert coordinator._controller.state.heat_request is None
