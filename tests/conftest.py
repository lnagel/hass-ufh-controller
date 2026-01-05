"""Common fixtures for UFH Controller tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import DATA_INSTANCE as RECORDER_DATA_INSTANCE
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
)

MOCK_CONTROLLER_ID = "test_controller"
MOCK_HEAT_REQUEST_ENTITY = "switch.test_heat_request"


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
            "heat_request_entity": MOCK_HEAT_REQUEST_ENTITY,
        },
        options={
            "timing": DEFAULT_TIMING,
            "zones": [
                {
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
                },
            ],
        },
        entry_id="test_entry_id",
        unique_id=MOCK_CONTROLLER_ID,
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
            "heat_request_entity": MOCK_HEAT_REQUEST_ENTITY,
        },
        options={
            "timing": DEFAULT_TIMING,
            "zones": [],
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
    """Mock the Recorder for all tests."""
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value={})

    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_instance,
    ):
        hass.data[RECORDER_DATA_INSTANCE] = mock_instance
        yield mock_instance
