"""Tests for outdoor temperature initialization in the coordinator."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_SUPPLY_TARGET_TEMP,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
    DEFAULT_TIMING,
    DOMAIN,
    INITIALIZING_TIMEOUT,
    SUBENTRY_TYPE_ZONE,
    ControllerStatus,
)
from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)
from tests.conftest import MOCK_ZONE_DATA


@pytest.fixture
def mock_config_entry_with_outdoor_temp() -> MockConfigEntry:
    """Return a mock config entry with outdoor temperature sensor configured."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller Outdoor",
        data={
            "name": "Test Controller Outdoor",
            "controller_id": "test_outdoor",
            "outdoor_temp_entity": "sensor.outdoor_temp",
            "outdoor_temp_warm": DEFAULT_OUTDOOR_TEMP_WARM,
            "outdoor_temp_cold": DEFAULT_OUTDOOR_TEMP_COLD,
            "supply_temp_warm": DEFAULT_SUPPLY_TEMP_WARM,
            "supply_temp_cold": DEFAULT_SUPPLY_TEMP_COLD,
            "supply_target_temp": DEFAULT_SUPPLY_TARGET_TEMP,
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_outdoor",
        unique_id="test_outdoor",
        subentries_data=[
            {
                "data": MOCK_ZONE_DATA,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    outdoor_temp: str | None = None,
) -> UFHControllerDataUpdateCoordinator:
    """Set up sensors, config entry, and return coordinator."""
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("switch.zone1_valve", "off")
    if outdoor_temp is not None:
        hass.states.async_set("sensor.outdoor_temp", outdoor_temp)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data.coordinator


async def test_waits_for_outdoor_temp_then_proceeds(
    hass: HomeAssistant,
    mock_config_entry_with_outdoor_temp: MockConfigEntry,
) -> None:
    """Controller stays INITIALIZING until outdoor temp arrives."""
    coord = await _setup(hass, mock_config_entry_with_outdoor_temp)
    assert coord.status == ControllerStatus.INITIALIZING

    # Outdoor temp arrives → transitions to NORMAL
    hass.states.async_set("sensor.outdoor_temp", "5.0")
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.status == ControllerStatus.NORMAL


async def test_degrades_after_timeout(
    hass: HomeAssistant,
    mock_config_entry_with_outdoor_temp: MockConfigEntry,
) -> None:
    """Controller reports DEGRADED after init timeout with fallback supply target."""
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("switch.zone1_valve", "off")
    mock_config_entry_with_outdoor_temp.add_to_hass(hass)
    coordinator = UFHControllerDataUpdateCoordinator(
        hass, mock_config_entry_with_outdoor_temp
    )
    coordinator._init_start = datetime.now(UTC) - timedelta(
        seconds=INITIALIZING_TIMEOUT + 10
    )

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert coordinator.status == ControllerStatus.DEGRADED
    assert coordinator.controller.state.outdoor_temp is None
    assert coordinator.controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP


async def test_degrades_when_outdoor_temp_lost_and_recovers(
    hass: HomeAssistant,
    mock_config_entry_with_outdoor_temp: MockConfigEntry,
) -> None:
    """Controller degrades when outdoor temp lost, recovers when it returns."""
    coord = await _setup(hass, mock_config_entry_with_outdoor_temp, outdoor_temp="5.0")
    assert coord.status == ControllerStatus.NORMAL

    hass.states.async_set("sensor.outdoor_temp", "unavailable")
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.status == ControllerStatus.DEGRADED

    hass.states.async_set("sensor.outdoor_temp", "8.0")
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.status == ControllerStatus.NORMAL


async def test_no_outdoor_sensor_configured_no_effect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Without outdoor temp sensor, controller init is unaffected."""
    coord = await _setup(hass, mock_config_entry)
    assert coord.status == ControllerStatus.NORMAL


async def test_zone_fail_safe_not_downgraded_by_outdoor_temp(
    hass: HomeAssistant,
    mock_config_entry_with_outdoor_temp: MockConfigEntry,
) -> None:
    """Zone FAIL_SAFE is not downgraded by outdoor temp logic."""
    hass.states.async_set("sensor.zone1_temp", "unavailable")
    hass.states.async_set("switch.zone1_valve", "off")
    mock_config_entry_with_outdoor_temp.add_to_hass(hass)
    coordinator = UFHControllerDataUpdateCoordinator(
        hass, mock_config_entry_with_outdoor_temp
    )
    past = datetime.now(UTC) - timedelta(seconds=INITIALIZING_TIMEOUT + 10)
    coordinator._init_start = past
    coordinator._controller.get_zone_runtime(
        "zone1"
    ).state.last_successful_update = past

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_recorder,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert coordinator.status == ControllerStatus.FAIL_SAFE
