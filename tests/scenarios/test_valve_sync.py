"""Test valve state synchronization with external changes."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
    ValveState,
)
from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)
from custom_components.ufh_controller.core.zone import ZoneAction


@pytest.fixture
def mock_config_entry_with_heat_request() -> MockConfigEntry:
    """Return a config entry with heat_request_entity configured."""
    zone_data: dict[str, Any] = {
        "id": "zone1",
        "name": "Test Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
    }
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller",
            "heat_request_entity": "switch.heat_request",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_id_hr",
        unique_id="test_controller_hr",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
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
    switch_calls.clear()

    # Simulate service call success - HA state reflects valve is now ON
    hass.states.async_set("switch.zone1_valve", "on")

    # Third refresh: valve ON, zone still needs heat → STAY_ON (no service call)
    freezer.tick(60)
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    # No service call - valve already in correct state
    assert len(switch_calls) == 0
    # Verify valve_state is tracked as ON
    runtime = coordinator._controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.state.valve_state == ValveState.ON


async def test_stay_off_updates_valve_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that STAY_OFF action updates valve_state to OFF."""
    freezer.move_to("2026-01-14 02:00:00+00:00")

    mock_config_entry.add_to_hass(hass)
    # Temperature above setpoint (21.0) - zone doesn't need heat
    hass.states.async_set("sensor.zone1_temp", "25.0")
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
        # First refresh: valve OFF, zone doesn't need heat → STAY_OFF
        # Force-update sends command even if state matches (dead-man-switch support)
        await coordinator.async_refresh()

    # First cycle force-update triggers service call even for STAY_OFF
    assert ("turn_off", "switch.zone1_valve") in switch_calls
    switch_calls.clear()

    # Second refresh in same observation period - no force-update needed
    freezer.tick(60)
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    # No service call - valve already in correct state and force-update done
    assert len(switch_calls) == 0
    # Verify valve_state is tracked as OFF
    runtime = coordinator._controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.state.valve_state == ValveState.OFF


@pytest.mark.parametrize(
    "initial_valve_state",
    [ValveState.UNAVAILABLE, ValveState.UNKNOWN, ValveState.OFF],
    ids=["unavailable", "unknown", "off"],
)
async def test_stay_on_resyncs_when_valve_not_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    initial_valve_state: ValveState,
) -> None:
    """
    Test STAY_ON re-sends turn_on when valve_state is not ON.

    If _execute_valve_actions_with_isolation receives STAY_ON but internal
    valve_state is not ON (uncertain or OFF), the valve should be turned on.
    """
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

    # First refresh to initialize the coordinator
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    switch_calls.clear()

    # Set valve_state and call _execute_valve_actions_with_isolation with STAY_ON
    runtime = coordinator._controller.get_zone_runtime("zone1")
    assert runtime is not None
    runtime.state.valve_state = initial_valve_state

    await coordinator._execute_valve_actions_with_isolation(
        {"zone1": ZoneAction.STAY_ON}
    )

    # Service call made to sync valve state
    assert ("turn_on", "switch.zone1_valve") in switch_calls
    # Verify valve_state is now tracked as ON
    assert runtime.state.valve_state == ValveState.ON


@pytest.mark.parametrize(
    "initial_valve_state",
    [ValveState.UNAVAILABLE, ValveState.UNKNOWN, ValveState.ON],
    ids=["unavailable", "unknown", "on"],
)
async def test_stay_off_resyncs_when_valve_not_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    initial_valve_state: ValveState,
) -> None:
    """
    Test STAY_OFF re-sends turn_off when valve_state is not OFF.

    If _execute_valve_actions_with_isolation receives STAY_OFF but internal
    valve_state is not OFF (uncertain or ON), the valve should be turned off.
    """
    freezer.move_to("2026-01-14 02:00:00+00:00")

    mock_config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "25.0")
    hass.states.async_set("switch.zone1_valve", "on")

    switch_calls: list[tuple[str, str]] = []

    async def track_switch_call(call: ServiceCall) -> None:
        switch_calls.append((call.service, call.data.get("entity_id", "")))

    hass.services.async_register("switch", "turn_on", track_switch_call)
    hass.services.async_register("switch", "turn_off", track_switch_call)

    coordinator = UFHControllerDataUpdateCoordinator(hass, mock_config_entry)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    # First refresh to initialize the coordinator
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    switch_calls.clear()

    # Set valve_state and call _execute_valve_actions_with_isolation with STAY_OFF
    runtime = coordinator._controller.get_zone_runtime("zone1")
    assert runtime is not None
    runtime.state.valve_state = initial_valve_state

    await coordinator._execute_valve_actions_with_isolation(
        {"zone1": ZoneAction.STAY_OFF}
    )

    # Service call made to sync valve state
    assert ("turn_off", "switch.zone1_valve") in switch_calls
    # Verify valve_state is now tracked as OFF
    assert runtime.state.valve_state == ValveState.OFF


@pytest.mark.parametrize(
    "valve_state",
    [STATE_UNAVAILABLE, STATE_UNKNOWN],
    ids=["unavailable", "unknown"],
)
async def test_valve_bad_state_logs_warning(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
    valve_state: str,
) -> None:
    """Test that a warning is logged when valve entity state is unavailable/unknown."""
    freezer.move_to("2026-01-14 02:00:00+00:00")
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
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a warning is logged when valve entity is not found."""
    freezer.move_to("2026-01-14 02:00:00+00:00")
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


async def test_force_update_sends_heat_request_even_when_matching(
    hass: HomeAssistant,
    mock_config_entry_with_heat_request: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that force-update sends heat_request command even if state matches."""
    freezer.move_to("2026-01-14 02:00:00+00:00")

    mock_config_entry_with_heat_request.add_to_hass(hass)
    # Zone doesn't need heat (temp above setpoint) - heat_request will be off
    hass.states.async_set("sensor.zone1_temp", "25.0")
    hass.states.async_set("switch.zone1_valve", "off")
    # Heat request already off - matches expected state
    hass.states.async_set("switch.heat_request", "off")

    switch_calls: list[tuple[str, str]] = []

    async def track_switch_call(call: ServiceCall) -> None:
        switch_calls.append((call.service, call.data.get("entity_id", "")))

    hass.services.async_register("switch", "turn_on", track_switch_call)
    hass.services.async_register("switch", "turn_off", track_switch_call)

    coordinator = UFHControllerDataUpdateCoordinator(
        hass, mock_config_entry_with_heat_request
    )

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        # First refresh: force-update sends command even though state matches
        await coordinator.async_refresh()

    # First cycle force-update triggers service call for heat_request
    # (turn_off because zone doesn't need heat)
    assert ("turn_off", "switch.heat_request") in switch_calls
    switch_calls.clear()

    # Second refresh in same observation period - no force-update
    freezer.tick(60)
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    # No heat_request call - state matches and force-update already done
    assert ("turn_off", "switch.heat_request") not in switch_calls
