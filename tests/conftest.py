"""Common fixtures for Underfloor Heating Controller tests."""

from collections.abc import Generator
from typing import TYPE_CHECKING, Any
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

if TYPE_CHECKING:
    from custom_components.ufh_controller.core.controller import HeatingController


# ---------------------------------------------------------------------------
# Test helper functions for zone setup (replacing removed delegator methods)
# ---------------------------------------------------------------------------


def setup_zone_pid(
    controller: "HeatingController",
    zone_id: str,
    current_temp: float | None,
    dt: float,
) -> float | None:
    """
    Set up zone with current temperature and update PID.

    This helper replaces the removed update_zone_pid() delegator method.
    Use this in tests to set up zone state before evaluating.

    Args:
        controller: HeatingController instance.
        zone_id: Zone identifier.
        current_temp: Current temperature (set directly, no EMA smoothing).
        dt: Time delta for PID update.

    Returns:
        The duty cycle, or None if zone not found.

    """
    runtime = controller.get_zone_runtime(zone_id)
    if runtime is None:
        return None
    runtime.state.current = current_temp
    return runtime.update_pid(dt, controller.mode)


def setup_zone_historical(  # noqa: PLR0913
    controller: "HeatingController",
    zone_id: str,
    *,
    period_state_avg: float,
    open_state_avg: float,
    window_recently_open: bool,
    elapsed_time: float,
) -> None:
    """
    Set up zone historical data for quota-based scheduling.

    This helper replaces the removed update_zone_historical() delegator method.
    Use this in tests to set up zone historical state before evaluating.

    Args:
        controller: HeatingController instance.
        zone_id: Zone identifier.
        period_state_avg: Average valve state since observation start (0.0-1.0).
        open_state_avg: Average valve state for open detection (0.0-1.0).
        window_recently_open: Whether any window was open recently.
        elapsed_time: Elapsed time since observation start in seconds.

    """
    runtime = controller.get_zone_runtime(zone_id)
    if runtime is None:
        return
    runtime.update_historical(
        period_state_avg=period_state_avg,
        open_state_avg=open_state_avg,
        window_recently_open=window_recently_open,
        elapsed_time=elapsed_time,
        observation_period=controller.config.timing.observation_period,
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
        "home": 21.0,
        "away": 16.0,
        "eco": 19.0,
        "comfort": 22.0,
        "boost": 25.0,
    },
}

MOCK_ZONE2_DATA: dict[str, Any] = {
    "id": "zone2",
    "name": "Test Zone 2",
    "circuit_type": "regular",
    "temp_sensor": "sensor.zone2_temp",
    "valve_switch": "switch.zone2_valve",
    "setpoint": DEFAULT_SETPOINT,
    "pid": DEFAULT_PID,
    "window_sensors": [],
    "presets": {
        "home": 21.0,
        "away": 16.0,
        "eco": 19.0,
        "comfort": 22.0,
        "boost": 25.0,
    },
}


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry with a zone subentry and DHW entity."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
            "dhw_active_entity": "binary_sensor.dhw_active",
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
def mock_config_entry_with_heat_request() -> MockConfigEntry:
    """Return a mock config entry with heat request entity configured."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": MOCK_CONTROLLER_ID,
            "heat_request_entity": "switch.heat_request",
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id=f"{MOCK_CONTROLLER_ID}_heat_request",
        unique_id=f"{MOCK_CONTROLLER_ID}_heat_request",
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


@pytest.fixture
def mock_config_entry_multiple_zones() -> MockConfigEntry:
    """Return a mock config entry with two zone subentries for isolation testing."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller Multi",
        data={
            "name": "Test Controller Multi",
            "controller_id": f"{MOCK_CONTROLLER_ID}_multi",
            "dhw_active_entity": "binary_sensor.dhw_active",
            "summer_mode_entity": "select.summer_mode",
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_id_multi",
        unique_id=f"{MOCK_CONTROLLER_ID}_multi",
        subentries_data=[
            {
                "data": MOCK_ZONE_DATA,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            },
            {
                "data": MOCK_ZONE2_DATA,
                "subentry_id": "subentry_zone2",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 2",
                "unique_id": "zone2",
            },
        ],
    )


@pytest.fixture
def mock_config_entry_all_entities() -> MockConfigEntry:
    """
    Return a mock config entry with all controller-level entities configured.

    Needed separately from mock_config_entry because adding these entities to
    the base fixture breaks tests that don't mock all required services.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller Full",
        data={
            "name": "Test Controller Full",
            "controller_id": f"{MOCK_CONTROLLER_ID}_full",
            "heat_request_entity": "switch.heat_request",
            "summer_mode_entity": "select.summer_mode",
            "dhw_active_entity": "binary_sensor.dhw_active",
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_id_full",
        unique_id=f"{MOCK_CONTROLLER_ID}_full",
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


@pytest.fixture
async def mock_temp_sensor(hass: HomeAssistant) -> None:
    """
    Set up mock temperature sensor and valve entity states.

    Use this fixture in tests that need the climate entity to be available.
    Without a temperature reading and available valve entity, zones cannot
    reach NORMAL status and climate entities are marked unavailable.
    """
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("switch.zone1_valve", "off")


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
