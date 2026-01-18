"""Tests for Underfloor Heating Controller coordinator persistence."""

from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
    OperationMode,
    ValveState,
    ZoneStatus,
)
from custom_components.ufh_controller.coordinator import (
    UFHControllerDataUpdateCoordinator,
)
from custom_components.ufh_controller.core.pid import PIDState


async def test_coordinator_saves_state_on_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator saves state when entry is unloaded."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Mock the save method
    with patch.object(
        coordinator, "async_save_state", new_callable=AsyncMock
    ) as mock_save:
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        mock_save.assert_called_once()


async def test_coordinator_loads_stored_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator loads stored state on first update."""
    stored_data = {
        "version": 1,
        "controller_mode": "flush",
        "zones": {
            "zone1": {
                # Full PID state to be restored
                "error": 2.0,
                "p_term": 30.0,
                "i_term": 45.5,
                "d_term": 1.5,
                "duty_cycle": 55.0,
                "temperature": 20.8,  # EMA-filtered temperature
                "display_temp": 20.8,  # Display temperature
                "zone_status": "normal",  # Saved zone status
                "last_successful_update": "2026-01-18T00:00:00+00:00",
            },
        },
    }

    # Set raw sensor to a different value to verify EMA restoration works
    hass.states.async_set("sensor.zone1_temp", "21.5")
    hass.states.async_set("switch.zone1_valve", "off")

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Check mode was restored
    assert coordinator.controller.mode == OperationMode.FLUSH

    # Check full PID state was restored (prevents sensors being unavailable)
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.pid.state is not None
    assert runtime.pid.state.error == 2.0
    assert runtime.pid.state.p_term == 30.0
    assert runtime.pid.state.i_term == 45.5
    assert runtime.pid.state.d_term == 1.5
    assert runtime.pid.state.duty_cycle == 55.0

    # Check EMA temperature was restored (value between stored and raw)
    assert runtime.state.current is not None
    assert 20.8 <= runtime.state.current <= 21.5

    # Check display_temp was restored directly (prevents entity unavailability)
    assert runtime.state.display_temp == 20.8

    # Check zone status was restored
    assert runtime.state.zone_status == ZoneStatus.NORMAL

    # Check last_successful_update was restored
    assert runtime.state.last_successful_update is not None

    # CRITICAL: Verify ALL entities are available (not Unknown)
    climate_state = hass.states.get("climate.test_zone_1_thermostat")
    assert climate_state is not None
    assert climate_state.state != "unavailable"
    assert climate_state.attributes.get("current_temperature") is not None

    # Verify sensors are available (duty_cycle, PID terms)
    duty_cycle_state = hass.states.get("sensor.test_zone_1_duty_cycle")
    assert duty_cycle_state is not None
    assert duty_cycle_state.state != "unavailable"
    assert duty_cycle_state.state == "55.0"

    # Verify binary sensors are available (heat_request, blocked)
    heat_request_state = hass.states.get("binary_sensor.test_zone_1_heat_request")
    assert heat_request_state is not None
    assert heat_request_state.state != "unavailable"


async def test_coordinator_save_state_format(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator saves state in expected format."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set some state
    coordinator.controller.mode = OperationMode.CYCLE
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Set PID state that should be persisted
    runtime.pid.set_state(
        PIDState(error=1.5, p_term=25.0, i_term=75.0, d_term=0.8, duty_cycle=65.0)
    )

    # Set temperature state that should be persisted
    runtime.state.current = 21.5
    runtime.state.display_temp = 21.5

    saved_data = None

    async def capture_save(data: dict) -> None:
        nonlocal saved_data
        saved_data = data

    with patch(
        "homeassistant.helpers.storage.Store.async_save", side_effect=capture_save
    ):
        await coordinator.async_save_state()

    assert saved_data is not None
    assert saved_data["version"] == 1
    assert saved_data["controller_mode"] == OperationMode.CYCLE
    assert "zones" in saved_data
    assert "zone1" in saved_data["zones"]

    # Verify full PID state is saved
    assert saved_data["zones"]["zone1"]["error"] == 1.5
    assert saved_data["zones"]["zone1"]["p_term"] == 25.0
    assert saved_data["zones"]["zone1"]["i_term"] == 75.0
    assert saved_data["zones"]["zone1"]["d_term"] == 0.8
    assert saved_data["zones"]["zone1"]["duty_cycle"] == 65.0

    # Verify temperature state is saved
    assert saved_data["zones"]["zone1"]["temperature"] == 21.5
    assert saved_data["zones"]["zone1"]["display_temp"] == 21.5

    # Verify zone_status is saved
    assert "zone_status" in saved_data["zones"]["zone1"]
    assert saved_data["zones"]["zone1"]["zone_status"] in [
        status.value for status in ZoneStatus
    ]

    # Verify last_successful_update is saved
    assert "last_successful_update" in saved_data["zones"]["zone1"]


async def test_coordinator_no_stored_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator handles no stored state gracefully."""
    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=None,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Should use default mode
    assert coordinator.controller.mode == OperationMode.HEAT

    # PID state should be None (no stored state, no updates yet)
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.pid.state is None


# =============================================================================
# Crash Recovery Tests
# =============================================================================


async def test_crash_recovery_mid_update_valve_remains_safe(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test valve state safety when crash occurs between evaluate and execute.

    Scenario: HA crashes after evaluate_zones() but before execute_valve_actions()
    Expected: On restart, valves should be recalculated and controlled safely.

    Key insight: evaluate_zones() updates in-memory valve_state, but the
    actual switch service call happens in execute_valve_actions(). If a crash
    occurs between these, the physical valve state may differ from the stored
    state. On restart, the system should recover correctly.
    """
    # Setup initial state with accumulated integral (zone wants heat)
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 1.0,
                "p_term": 50.0,
                "i_term": 50.0,  # Significant integral = heating demand
                "d_term": 0.0,
                "duty_cycle": 100.0,
                "setpoint": 22.0,
                "enabled": True,
            },
        },
    }

    # Set up temperature sensor (cold room = needs heat)
    hass.states.async_set("sensor.zone1_temp", "19.0")

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # After setup and first refresh, integral should be close to the stored value
    # (some increase expected due to PID update with positive error)
    # The key point is that the stored integral was successfully restored
    # and used as the starting point for continued integration
    assert runtime.pid.state.i_term >= 50.0  # Started from stored value

    # The system should recalculate and determine valve action
    # Since temperature (19°C) is below setpoint (22°C) and integral is positive,
    # the controller will produce a positive duty cycle
    # Key safety check: the system doesn't crash and handles the recovery
    assert runtime.pid.state.duty_cycle is not None
    # Duty cycle should be positive given the temperature error
    assert runtime.pid.state.duty_cycle > 0

    # Additional safety check: another refresh cycle completes successfully
    await coordinator.async_refresh()
    assert runtime.pid.state.duty_cycle is not None
    assert runtime.pid.state.duty_cycle > 0


async def test_crash_recovery_preserves_valve_off_when_duty_cycle_zero(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that valves stay off after restart when duty cycle is zero.

    Scenario: Room is already warm, duty cycle is 0, system restarts.
    Expected: Valve should remain off, preventing unnecessary heating.
    """
    # Setup: room at setpoint, no heating needed
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 0.0,
                "p_term": 0.0,
                "i_term": 0.0,
                "d_term": 0.0,
                "duty_cycle": 0.0,
                "setpoint": 20.0,
                "enabled": True,
            },
        },
    }

    # Temperature at setpoint
    hass.states.async_set("sensor.zone1_temp", "20.5")

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Trigger update
    await coordinator.async_refresh()

    # Temperature is above setpoint, so no heating demand
    assert runtime.pid.state is not None
    assert runtime.pid.state.error < 0  # Negative error = above setpoint
    # Valve should be off
    assert runtime.state.valve_state == ValveState.OFF


async def test_crash_recovery_no_integral_windup_during_disabled_period(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that integral doesn't wind up during disabled periods after restart.

    Scenario: Zone was disabled before crash, system restarts with zone still disabled.
    Expected: Integral should not accumulate while zone is disabled.
    """
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 0.5,
                "p_term": 25.0,
                "i_term": 25.0,
                "d_term": 0.0,
                "duty_cycle": 50.0,
                "setpoint": 22.0,
                "enabled": False,  # Zone was disabled
            },
        },
    }

    # Cold room - would accumulate integral if enabled
    hass.states.async_set("sensor.zone1_temp", "18.0")

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Verify zone is disabled
    assert runtime.state.enabled is False

    # Record integral before update
    integral_before = runtime.pid.state.i_term

    # Trigger multiple updates
    for _ in range(3):
        await coordinator.async_refresh()

    # Integral should NOT have increased (PID paused for disabled zones)
    assert runtime.pid.state.i_term == integral_before


async def test_crash_recovery_no_integral_windup_with_window_open(
    hass: HomeAssistant,
) -> None:
    """
    Test that integral doesn't wind up when window is open after restart.

    Scenario: Window was open before crash, still open after restart.
    Expected: Integral should not accumulate while window is open.
    """
    # Create config entry with window sensor
    zone_data = {
        "id": "zone1",
        "name": "Test Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": ["binary_sensor.zone1_window"],
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller_window",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_window",
        unique_id="test_controller_window",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1_window",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )

    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 1.0,
                "p_term": 50.0,
                "i_term": 30.0,
                "d_term": 0.0,
                "duty_cycle": 80.0,
                "setpoint": 22.0,
                "enabled": True,
            },
        },
    }

    # Cold room but window is open
    hass.states.async_set("sensor.zone1_temp", "18.0")
    hass.states.async_set("binary_sensor.zone1_window", "on")  # Window open

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Record integral before update
    integral_before = runtime.pid.state.i_term

    # Trigger multiple updates
    for _ in range(3):
        await coordinator.async_refresh()

    # Integral should NOT have increased (PID paused when window open)
    assert runtime.pid.state.i_term == integral_before

    # Clean up
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_crash_recovery_state_consistency_after_multiple_restarts(
    hass: HomeAssistant,
) -> None:
    """
    Test state consistency after multiple simulated restarts.

    Scenario: Multiple restart cycles with state persistence.
    Expected: State should remain consistent and not drift.
    """
    zone_data = {
        "id": "zone1",
        "name": "Test Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller_restart",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_restart",
        unique_id="test_controller_restart",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1_restart",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )

    hass.states.async_set("sensor.zone1_temp", "19.5")

    # First "boot" - no stored state
    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=None,
    ):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Run several update cycles to build up some state
    for _ in range(5):
        await coordinator.async_refresh()

    # Capture state after first "session"
    integral_session1 = runtime.pid.state.i_term
    setpoint_session1 = runtime.state.setpoint
    pid_state = runtime.pid.state

    # Prepare state for "second boot"
    saved_state = {
        "version": 1,
        "controller_mode": coordinator.controller.mode,
        "zones": {
            "zone1": {
                "error": pid_state.error,
                "p_term": pid_state.p_term,
                "i_term": pid_state.i_term,
                "d_term": pid_state.d_term,
                "duty_cycle": pid_state.duty_cycle,
                "setpoint": setpoint_session1,
                "enabled": runtime.state.enabled,
            },
        },
    }

    # Unload to simulate shutdown
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    # "Second boot" - restore from saved state
    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=saved_state,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Verify state was restored correctly
    # After the second boot, the integral should be >= the saved value
    # (it may have increased slightly during the first refresh)
    assert runtime.pid.state.i_term >= integral_session1
    assert runtime.state.setpoint == setpoint_session1

    # Cleanup
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_crash_recovery_valve_action_sequence_integrity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that valve action sequence completes atomically.

    This tests that evaluate_zones() and execute_valve_actions() work together
    correctly, and that the state saved after the update reflects the actual
    actions taken.
    """
    hass.states.async_set("sensor.zone1_temp", "18.0")  # Cold room

    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 2.0,
                "p_term": 100.0,
                "i_term": 60.0,  # High demand
                "d_term": 0.0,
                "duty_cycle": 100.0,
                "setpoint": 22.0,
                "enabled": True,
            },
        },
    }

    saved_states: list[dict] = []

    async def capture_save(data: dict) -> None:
        saved_states.append(data.copy())

    with (
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=stored_data,
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_save",
            side_effect=capture_save,
        ),
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator

        # Trigger update cycle which will evaluate and execute
        await coordinator.async_refresh()

    # At least one save should have occurred
    assert len(saved_states) >= 1

    # The saved state should reflect the post-update state
    last_saved = saved_states[-1]
    assert "zones" in last_saved
    assert "zone1" in last_saved["zones"]

    # Integral should have been updated (accumulated more error)
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Verify the saved integral matches the current state
    # (proving state was saved AFTER the full update completed)
    assert last_saved["zones"]["zone1"]["i_term"] == runtime.pid.state.i_term


async def test_crash_recovery_mode_preserved_across_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """
    Test that operation mode is preserved across restarts.

    Scenario: Mode was set to 'flush' before crash.
    Expected: Mode should be 'flush' after restart.
    """
    for test_mode in [
        OperationMode.HEAT,
        OperationMode.FLUSH,
        OperationMode.CYCLE,
        OperationMode.ALL_ON,
        OperationMode.ALL_OFF,
    ]:
        stored_data = {
            "version": 1,
            "controller_mode": test_mode,
            "zones": {
                "zone1": {
                    "error": 0.0,
                    "p_term": 0.0,
                    "i_term": 0.0,
                    "d_term": 0.0,
                    "duty_cycle": 0.0,
                    "setpoint": 21.0,
                    "enabled": True,
                },
            },
        }

        hass.states.async_set("sensor.zone1_temp", "20.0")

        with patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=stored_data,
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data.coordinator
        assert coordinator.controller.mode == test_mode

        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_crash_recovery_partial_zone_state_restoration(
    hass: HomeAssistant,
) -> None:
    """
    Test recovery when stored state has partial/missing zone data.

    Scenario: Stored state has incomplete zone information.
    Expected: System should use defaults for missing values.
    """
    zone_data = {
        "id": "zone1",
        "name": "Test Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller_partial",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_partial",
        unique_id="test_controller_partial",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1_partial",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )

    # Stored state with only some PID fields (uses defaults for missing)
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "i_term": 35.0,
                "duty_cycle": 35.0,  # Required to trigger restore
                # Missing: error, p_term, d_term, setpoint, enabled
            },
        },
    }

    hass.states.async_set("sensor.zone1_temp", "20.0")

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Integral should be restored and then possibly updated by first refresh
    # The key point is it started from the stored value (35.0)
    assert runtime.pid.state.i_term >= 35.0

    # setpoint should be the default from config
    assert runtime.state.setpoint == 21.0  # DEFAULT_SETPOINT["default"]

    # enabled should default to True
    assert runtime.state.enabled is True

    # Cleanup
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_flush_enabled_saved_in_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that flush_enabled is saved in coordinator state."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Set flush_enabled to True
    coordinator.controller.state.flush_enabled = True

    saved_data = None

    async def capture_save(data: dict) -> None:
        nonlocal saved_data
        saved_data = data

    with patch(
        "homeassistant.helpers.storage.Store.async_save", side_effect=capture_save
    ):
        await coordinator.async_save_state()

    assert saved_data is not None
    assert "flush_enabled" in saved_data
    assert saved_data["flush_enabled"] is True

    # Also test with False
    coordinator.controller.state.flush_enabled = False

    with patch(
        "homeassistant.helpers.storage.Store.async_save", side_effect=capture_save
    ):
        await coordinator.async_save_state()

    assert saved_data["flush_enabled"] is False


async def test_flush_enabled_restored_from_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that flush_enabled is restored from stored state."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "flush_enabled": True,
        "zones": {
            "zone1": {
                "error": 0.0,
                "p_term": 0.0,
                "i_term": 0.0,
                "d_term": 0.0,
                "duty_cycle": 0.0,
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Check flush_enabled was restored
    assert coordinator.controller.state.flush_enabled is True


async def test_flush_enabled_defaults_to_false_when_not_stored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that flush_enabled defaults to False when not in stored state."""
    # Stored data without flush_enabled (simulates old storage format)
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 0.0,
                "p_term": 0.0,
                "i_term": 0.0,
                "d_term": 0.0,
                "duty_cycle": 0.0,
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # flush_enabled should remain at default (False)
    assert coordinator.controller.state.flush_enabled is False


async def test_crash_recovery_stale_zone_in_stored_state(
    hass: HomeAssistant,
) -> None:
    """
    Test recovery when stored state has zone that no longer exists.

    Scenario: A zone was removed from config but still exists in stored state.
    Expected: System should ignore the stale zone data gracefully.
    """
    zone_data = {
        "id": "zone1",
        "name": "Test Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller_stale",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_stale",
        unique_id="test_controller_stale",
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_zone1_stale",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Test Zone 1",
                "unique_id": "zone1",
            }
        ],
    )

    # Stored state has a zone that doesn't exist in current config
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 0.5,
                "p_term": 10.0,
                "i_term": 20.0,
                "d_term": 0.0,
                "duty_cycle": 30.0,
                "setpoint": 21.0,
                "enabled": True,
            },
            "zone_deleted": {  # This zone no longer exists
                "error": 1.0,
                "p_term": 50.0,
                "i_term": 50.0,
                "d_term": 0.0,
                "duty_cycle": 100.0,
                "setpoint": 22.0,
                "enabled": True,
            },
        },
    }

    hass.states.async_set("sensor.zone1_temp", "20.0")

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator

    # Should only have zone1
    assert coordinator.controller.zone_ids == ["zone1"]

    # zone1 should be restored correctly
    # (integral may have increased after first refresh)
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None
    assert runtime.pid.state.i_term >= 20.0  # Started from stored value

    # zone_deleted should not exist
    assert coordinator.controller.get_zone_runtime("zone_deleted") is None

    # Cleanup
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_restore_with_invalid_zone_status(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator handles invalid zone_status gracefully."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 1.0,
                "p_term": 25.0,
                "i_term": 30.0,
                "d_term": 0.5,
                "duty_cycle": 50.0,
                "zone_status": "invalid_status",  # Invalid status
            },
        },
    }

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value=stored_data,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    runtime = coordinator.controller.get_zone_runtime("zone1")
    assert runtime is not None

    # Should remain INITIALIZING when invalid status provided
    assert runtime.state.zone_status == ZoneStatus.INITIALIZING


async def test_restore_with_invalid_timestamp(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator handles invalid last_successful_update gracefully."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                "error": 1.0,
                "p_term": 25.0,
                "i_term": 30.0,
                "d_term": 0.5,
                "duty_cycle": 50.0,
                "zone_status": "normal",
                "temperature": 21.0,
                "display_temp": 21.0,
                "last_successful_update": "invalid-timestamp",  # Invalid format
            },
        },
    }

    # Set up sensors so zone doesn't go into degraded mode
    hass.states.async_set("sensor.zone1_temp", "21.0")
    hass.states.async_set("switch.zone1_valve", "off")

    # Capture state immediately after restoration, before first update
    original_restore_method = UFHControllerDataUpdateCoordinator._restore_zone_state

    restored_timestamp = None

    def capture_restore(self: Any, zone_id: str, zone_state: dict[str, Any]) -> None:
        nonlocal restored_timestamp
        original_restore_method(self, zone_id, zone_state)
        runtime = self._controller.get_zone_runtime(zone_id)
        if runtime:
            restored_timestamp = runtime.state.last_successful_update

    with (
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=stored_data,
        ),
        patch.object(
            UFHControllerDataUpdateCoordinator,
            "_restore_zone_state",
            capture_restore,
        ),
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify invalid timestamp was not restored (remained None after restore)
    assert restored_timestamp is None


async def test_restore_without_optional_fields(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator handles missing optional fields gracefully."""
    stored_data = {
        "version": 1,
        "controller_mode": "heat",
        "zones": {
            "zone1": {
                # Only PID state, no optional fields
                "error": 1.0,
                "p_term": 25.0,
                "i_term": 30.0,
                "d_term": 0.5,
                "duty_cycle": 50.0,
                # Missing: temperature, display_temp, zone_status,
                # last_successful_update
            },
        },
    }

    # Capture state immediately after restoration, before first update
    original_restore_method = UFHControllerDataUpdateCoordinator._restore_zone_state

    restored_state = None

    def capture_restore(self: Any, zone_id: str, zone_state: dict[str, Any]) -> None:
        nonlocal restored_state
        original_restore_method(self, zone_id, zone_state)
        runtime = self._controller.get_zone_runtime(zone_id)
        if runtime:
            restored_state = {
                "current": runtime.state.current,
                "display_temp": runtime.state.display_temp,
                "zone_status": runtime.state.zone_status,
                "last_successful_update": runtime.state.last_successful_update,
            }

    with (
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=stored_data,
        ),
        patch.object(
            UFHControllerDataUpdateCoordinator,
            "_restore_zone_state",
            capture_restore,
        ),
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify optional fields remained as defaults when not in storage
    assert restored_state is not None
    assert restored_state["current"] is None
    assert restored_state["display_temp"] is None
    assert restored_state["zone_status"] == ZoneStatus.INITIALIZING
    assert restored_state["last_successful_update"] is None
