"""Common fixtures for UFH Controller tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import (
    DATA_INSTANCE as RECORDER_DATA_INSTANCE,
)
from homeassistant.helpers.recorder import (
    DATA_RECORDER,
    RecorderData,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
)

MOCK_CONTROLLER_ID = "test_controller"

MOCK_ZONE_DATA: dict[str, Any] = {
    "id": "zone1",
    "name": "Test Zone 1",
    "circuit_type": "regular",
    "temp_sensor": "sensor.zone1_temp",
    "valve_switch": "switch.zone1_valve",
    "setpoint": DEFAULT_SETPOINT,
    "pid": DEFAULT_PID,
    "window_sensors": [],
    "presets": {
        "comfort": {"setpoint": 22.0},
        "eco": {"setpoint": 19.0},
        "away": {"setpoint": 16.0},
        "boost": {"setpoint": 25.0, "pid_enabled": False},
    },
}


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry with a zone subentry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_id",
        unique_id=MOCK_CONTROLLER_ID,
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


@pytest.fixture
def mock_config_entry_no_zones() -> MockConfigEntry:
    """Return a mock config entry without zones."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_id_no_zones",
        unique_id=f"{MOCK_CONTROLLER_ID}_no_zones",
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable custom integrations for all tests."""


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Allow lingering timers for coordinator updates."""
    return True


@pytest.fixture
def platforms() -> list[Platform]:
    """Return the platforms to load."""
    return [
        Platform.CLIMATE,
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
        Platform.SELECT,
        Platform.SWITCH,
    ]


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Mock setting up a config entry."""
    with patch(
        "custom_components.ufh_controller.async_setup_entry",
        return_value=True,
    ):
        yield


@pytest.fixture(autouse=True)
def mock_recorder(hass: HomeAssistant) -> Generator[MagicMock]:
    """
    Mock the Recorder for all tests.

    This fixture sets up both DATA_RECORDER (required for recorder initialization)
    and DATA_INSTANCE (required for state history queries), and mocks the recorder
    component's async_setup to succeed without actually starting the recorder.
    """
    # Create the RecorderData with a completed db_connected future
    recorder_data = RecorderData()
    recorder_data.db_connected.set_result(True)
    hass.data[DATA_RECORDER] = recorder_data

    # Create a mock recorder instance for history queries
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value={})

    async def mock_recorder_setup(hass: HomeAssistant, config: dict) -> bool:
        """Mock recorder setup that succeeds without starting the actual recorder."""
        hass.data[RECORDER_DATA_INSTANCE] = mock_instance
        return True

    with (
        patch(
            "homeassistant.components.recorder.async_setup",
            side_effect=mock_recorder_setup,
        ),
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_instance,
        ),
    ):
        yield mock_instance
