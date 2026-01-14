"""
Tests for zone initial state - sensors should be unavailable until calculated.

This module tests that:
1. Zone PID values are None (not 0.0) when first initialized
2. Sensors are marked unavailable (not just unknown) before first PID calculation

Using unavailable state prevents Home Assistant from recording null values to
history during restarts, which was causing incorrect history data.
"""

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    HeatingController,
    ZoneConfig,
)
from custom_components.ufh_controller.core.zone import ZoneState
from tests.conftest import setup_zone_pid


class TestZoneStateInitialization:
    """
    Test that ZoneState and PIDController fields initialize to None (not 0.0).

    This prevents incorrect 0.0 values from being recorded in HA history
    during restarts before actual values are calculated.
    """

    def test_zone_state_current_is_none(self) -> None:
        """Test current temperature is None when no reading available."""
        state = ZoneState(zone_id="test_zone")
        assert state.current is None


class TestControllerZoneInitialization:
    """Test that HeatingController initializes zones with None PID values."""

    @pytest.fixture
    def basic_config(self) -> ControllerConfig:
        """Create a basic controller configuration."""
        return ControllerConfig(
            controller_id="heating",
            name="Heating Controller",
            zones=[
                ZoneConfig(
                    zone_id="living_room",
                    name="Living Room",
                    temp_sensor="sensor.living_room_temp",
                    valve_switch="switch.living_room_valve",
                ),
            ],
        )

    def test_controller_zone_pid_fields_start_as_none(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test zone PID state is None before first PID update."""
        controller = HeatingController(basic_config)

        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None

        # Before any PID calculation, PID state should be None
        assert runtime.pid.state is None, "PID state should be None before first update"

    def test_controller_zone_pid_fields_have_values_after_update(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test zone PID fields have float values after PID update."""
        controller = HeatingController(basic_config)
        controller.set_zone_setpoint("living_room", 22.0)

        # Perform a PID update with a valid temperature
        setup_zone_pid(controller, "living_room", 20.0, 60.0)

        runtime = controller.get_zone_runtime("living_room")
        assert runtime is not None
        assert runtime.pid.state is not None

        # After PID calculation, these should be floats (not None)
        assert isinstance(runtime.pid.state.error, float), (
            "error should be a float after update"
        )
        assert isinstance(runtime.pid.state.p_term, float), (
            "p_term should be a float after update"
        )
        assert isinstance(runtime.pid.state.i_term, float), (
            "i_term should be a float after update"
        )
        assert isinstance(runtime.pid.state.d_term, float), (
            "d_term should be a float after update"
        )
        assert isinstance(runtime.pid.state.duty_cycle, float), (
            "duty_cycle should be a float after update"
        )


class TestSensorInitialValues:
    """
    Test that sensors are unavailable before PID calculation.

    Using STATE_UNAVAILABLE (instead of STATE_UNKNOWN) prevents Home Assistant
    from recording null values to history during restarts.
    """

    async def test_duty_cycle_sensor_unavailable_before_calculation(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test duty cycle sensor is unavailable before first PID calculation."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.test_zone_1_duty_cycle")
        assert state is not None
        # Sensor should be unavailable (not unknown) to prevent history recording
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor should be unavailable before PID calculation, got {state.state}"
        )

    async def test_pid_error_sensor_unavailable_before_calculation(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test PID error sensor is unavailable before first PID calculation."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.test_zone_1_pid_error")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor should be unavailable before PID calculation, got {state.state}"
        )

    async def test_pid_proportional_sensor_unavailable_before_calculation(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test PID proportional sensor is unavailable before first PID calculation."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.test_zone_1_pid_proportional")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor should be unavailable before PID calculation, got {state.state}"
        )

    async def test_pid_integral_sensor_unavailable_before_calculation(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test PID integral sensor is unavailable before first PID calculation."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.test_zone_1_pid_integral")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor should be unavailable before PID calculation, got {state.state}"
        )

    async def test_pid_derivative_sensor_unavailable_before_calculation(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test PID derivative sensor is unavailable before first PID calculation."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.test_zone_1_pid_derivative")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE, (
            f"Sensor should be unavailable before PID calculation, got {state.state}"
        )
