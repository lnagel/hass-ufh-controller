"""Test valve state synchronization with external changes."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)


async def test_valve_restored_when_externally_turned_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """
    Test that valve is restored when something external turns it off.

    Scenario: Zone at 100% duty cycle, valve ON, then external factor
    turns valve OFF. Next update should detect mismatch and restore valve.

    Note: Uses frozen time to avoid flakiness. The zone evaluation logic freezes
    valve state near the end of observation periods (last 9 minutes of 2-hour
    periods). Without time mocking, this test fails ~7.5% of the time.
    """
    # Freeze time at start of observation period to ensure valve changes are allowed
    freezer.move_to("2026-01-14 02:00:00+00:00")

    mock_config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "18.0")
    hass.states.async_set("switch.zone1_valve", "off")

    switch_calls: list[tuple[str, str]] = []

    async def track_switch_call(call: ServiceCall) -> None:
        switch_calls.append((call.service, call.data.get("entity_id", "")))

    hass.services.async_register("switch", "turn_on", track_switch_call)
    hass.services.async_register("switch", "turn_off", track_switch_call)

    coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    assert ("turn_on", "switch.zone1_valve") in switch_calls
    switch_calls.clear()

    # External factor turns valve off
    hass.states.async_set("switch.zone1_valve", "off")

    # Advance time slightly for second refresh
    freezer.tick(60)

    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    # Valve should be restored
    assert ("turn_on", "switch.zone1_valve") in switch_calls


@pytest.mark.parametrize(
    "valve_state",
    [STATE_UNAVAILABLE, STATE_UNKNOWN],
    ids=["unavailable", "unknown"],
)
async def test_valve_bad_state_logs_warning(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    valve_state: str,
) -> None:
    """Test that a warning is logged when valve entity state is unavailable/unknown."""
    mock_config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "18.0")
    hass.states.async_set("switch.zone1_valve", valve_state)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    with (
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ),
        caplog.at_level(logging.WARNING),
    ):
        await coordinator.async_refresh()

    # Check for warning log about valve state (either "unavailable" or "unknown")
    assert any(
        ("unavailable" in record.message.lower() or "unknown" in record.message.lower())
        and "switch.zone1_valve" in record.message
        for record in caplog.records
    )


async def test_valve_not_found_logs_warning(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a warning is logged when valve entity is not found."""
    mock_config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "18.0")
    # Do NOT set valve state - entity doesn't exist

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    with (
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ),
        caplog.at_level(logging.WARNING),
    ):
        await coordinator.async_refresh()

    assert any(
        "not found" in record.message.lower() and "switch.zone1_valve" in record.message
        for record in caplog.records
    )
