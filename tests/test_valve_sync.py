"""Test valve state synchronization with external changes."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)


async def test_valve_restored_when_externally_turned_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that valve is restored when something external turns it off.

    Scenario: Zone at 100% duty cycle, valve ON, then external factor
    turns valve OFF. Next update should detect mismatch and restore valve.
    """
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

    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()

    # Valve should be restored
    assert ("turn_on", "switch.zone1_valve") in switch_calls
