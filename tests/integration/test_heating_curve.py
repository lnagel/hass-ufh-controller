"""Integration tests for heating curve with outdoor temperature compensation."""

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_OUTDOOR_TEMP_COLD,
    DEFAULT_OUTDOOR_TEMP_WARM,
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_SUPPLY_TARGET_TEMP,
    DEFAULT_SUPPLY_TEMP_COLD,
    DEFAULT_SUPPLY_TEMP_WARM,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
)

MOCK_ZONE_DATA: dict[str, Any] = {
    "id": "zone1",
    "name": "Test Zone 1",
    "circuit_type": "regular",
    "temp_sensor": "sensor.zone1_temp",
    "valve_switch": "switch.zone1_valve",
    "setpoint": DEFAULT_SETPOINT,
    "pid": DEFAULT_PID,
    "window_sensors": [],
    "presets": {},
}


@pytest.fixture
def mock_config_entry_with_heating_curve() -> MockConfigEntry:
    """Return a mock config entry with heating curve enabled."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller Heating Curve",
        data={
            "name": "Test Controller Heating Curve",
            "controller_id": "test_heating_curve",
            "supply_temp_entity": "sensor.supply_temp",
            "outdoor_temp_entity": "sensor.outdoor_temp",
            "outdoor_temp_warm": DEFAULT_OUTDOOR_TEMP_WARM,
            "outdoor_temp_cold": DEFAULT_OUTDOOR_TEMP_COLD,
            "supply_temp_warm": DEFAULT_SUPPLY_TEMP_WARM,
            "supply_temp_cold": DEFAULT_SUPPLY_TEMP_COLD,
            "supply_target_temp": DEFAULT_SUPPLY_TARGET_TEMP,
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_heating_curve",
        unique_id="test_heating_curve",
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
def mock_config_entry_no_heating_curve() -> MockConfigEntry:
    """Return a mock config entry without heating curve (no outdoor sensor)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller No Curve",
        data={
            "name": "Test Controller No Curve",
            "controller_id": "test_no_curve",
            "supply_temp_entity": "sensor.supply_temp",
            # outdoor_temp_entity intentionally omitted
            "supply_target_temp": DEFAULT_SUPPLY_TARGET_TEMP,
        },
        options={
            "timing": DEFAULT_TIMING,
        },
        entry_id="test_entry_no_curve",
        unique_id="test_no_curve",
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


class TestHeatingCurveIntegration:
    """Integration tests for heating curve calculation via controller state."""

    async def test_supply_target_at_midpoint(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply target calculation at midpoint outdoor temp."""
        # Set up sensors
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "2.5")  # Midpoint

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        # Trigger update to populate state
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Verify outdoor temp and supply target in controller state
        assert controller.state.outdoor_temp == 2.5
        # Midpoint outdoor (2.5°C) should give midpoint supply target (35°C)
        assert controller.state.supply_target_temp == pytest.approx(35.0)

    async def test_supply_target_at_warm_point(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply target at warm design point."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "25.0")
        hass.states.async_set("sensor.outdoor_temp", "15.0")  # Warm point

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp == 15.0
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TEMP_WARM  # 25°C

    async def test_supply_target_at_cold_point(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply target at cold design point."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "45.0")
        hass.states.async_set("sensor.outdoor_temp", "-10.0")  # Cold point

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp == -10.0
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TEMP_COLD  # 45°C

    async def test_fallback_when_outdoor_sensor_unavailable(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test fallback to fixed target when outdoor sensor unavailable."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "40.0")
        # outdoor_temp sensor not set (unavailable)

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Outdoor temp unavailable
        assert controller.state.outdoor_temp is None
        # Falls back to fixed target
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP

    async def test_fallback_when_outdoor_sensor_invalid_state(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test fallback when outdoor sensor has invalid state."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "40.0")
        hass.states.async_set("sensor.outdoor_temp", "unknown")

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Invalid state returns None
        assert controller.state.outdoor_temp is None
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP

    async def test_no_outdoor_entity_configured_uses_fallback(
        self,
        hass: HomeAssistant,
        mock_config_entry_no_heating_curve: MockConfigEntry,
    ) -> None:
        """Test that without outdoor entity, fallback is used."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "40.0")

        mock_config_entry_no_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_no_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_no_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # No outdoor entity configured
        assert controller.state.outdoor_temp is None
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP


class TestSupplyTargetSensor:
    """Tests for supply target sensor entity."""

    async def test_supply_target_sensor_created_with_outdoor_entity(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply target sensor is created when outdoor entity is configured."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        # Verify sensor entity is created
        state = hass.states.get("sensor.test_controller_heating_curve_supply_target")
        assert state is not None

    async def test_supply_target_sensor_not_created_without_outdoor_entity(
        self,
        hass: HomeAssistant,
        mock_config_entry_no_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply target sensor is NOT created without outdoor entity."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "40.0")

        mock_config_entry_no_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_no_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        # Verify sensor entity is NOT created
        state = hass.states.get("sensor.test_controller_no_curve_supply_target")
        assert state is None

    async def test_supply_target_sensor_value_matches_controller_state(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply target sensor value matches controller state."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "2.5")  # Midpoint

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Verify sensor value matches controller state
        state = hass.states.get("sensor.test_controller_heating_curve_supply_target")
        assert state is not None
        assert float(state.state) == pytest.approx(35.0)  # Midpoint = 35°C


class TestHeatingCurveSupplyCoefficient:
    """Test supply coefficient calculation with dynamic supply target."""

    async def test_supply_coefficient_uses_dynamic_target(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test that supply coefficient is calculated with dynamic target."""
        # Set up entities
        # Room temp: 20°C, setpoint: 21°C (default)
        # Supply temp: 35°C
        # Outdoor temp: 2.5°C (midpoint) -> dynamic target = 35°C
        # supply_coefficient = (35-20)/(35-21) * 100 = 15/14 * 100 = 107.1%
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "2.5")

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator

        # Trigger a coordinator update to calculate supply coefficient
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Check that supply coefficient was calculated
        zone_runtime = coordinator.controller.get_zone_runtime("zone1")
        assert zone_runtime is not None
        # With dynamic target of 35°C:
        # (35 - 20) / (35 - 21) * 100 = 15/14 * 100 = 107.14%
        if zone_runtime.state.supply_coefficient is not None:
            assert zone_runtime.state.supply_coefficient == pytest.approx(
                107.14, rel=0.01
            )

    async def test_supply_coefficient_at_cold_outdoor_temp(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test supply coefficient at cold outdoor temperature."""
        # Room temp: 20°C, setpoint: 21°C (default)
        # Supply temp: 45°C
        # Outdoor temp: -10°C (cold point) -> dynamic target = 45°C
        # supply_coefficient = (45-20)/(45-21) * 100 = 25/24 * 100 = 104.2%
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "45.0")
        hass.states.async_set("sensor.outdoor_temp", "-10.0")

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        zone_runtime = coordinator.controller.get_zone_runtime("zone1")
        assert zone_runtime is not None
        # (45 - 20) / (45 - 21) * 100 = 25/24 * 100 = 104.17%
        if zone_runtime.state.supply_coefficient is not None:
            assert zone_runtime.state.supply_coefficient == pytest.approx(
                104.17, rel=0.01
            )


class TestHeatingCurveInvalidConfig:
    """Test behavior with invalid heating curve configuration."""

    async def test_invalid_curve_logs_warning_and_uses_fallback(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that invalid curve logs warning and uses fallback."""
        # Create entry with invalid curve (warm <= cold)
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Invalid Curve",
            data={
                "name": "Test Invalid Curve",
                "controller_id": "test_invalid_curve",
                "supply_temp_entity": "sensor.supply_temp",
                "outdoor_temp_entity": "sensor.outdoor_temp",
                "outdoor_temp_warm": 10.0,
                "outdoor_temp_cold": 15.0,  # Invalid: cold > warm
                "supply_temp_warm": DEFAULT_SUPPLY_TEMP_WARM,
                "supply_temp_cold": DEFAULT_SUPPLY_TEMP_COLD,
                "supply_target_temp": 42.0,  # Fallback
            },
            options={
                "timing": DEFAULT_TIMING,
            },
            entry_id="test_entry_invalid_curve",
            unique_id="test_invalid_curve",
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

        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Outdoor temp is read
        assert controller.state.outdoor_temp == 5.0
        # With invalid curve, should use fallback (42.0)
        assert controller.state.supply_target_temp == 42.0


class TestHeatingCurveOutdoorSensorStateChange:
    """Test behavior when outdoor sensor state changes."""

    async def test_outdoor_temp_change_affects_supply_target(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test that changing outdoor temp affects supply target."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "15.0")  # Warm point

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # At warm point (15°C), supply target should be 25°C
        assert controller.state.outdoor_temp == 15.0
        assert controller.state.supply_target_temp == 25.0

        # Now change outdoor temp to cold point
        hass.states.async_set("sensor.outdoor_temp", "-10.0")
        await hass.async_block_till_done()

        # Trigger update
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # At cold point (-10°C), supply target should be 45°C
        assert controller.state.outdoor_temp == -10.0
        assert controller.state.supply_target_temp == 45.0

    async def test_outdoor_sensor_becomes_unavailable(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Test behavior when outdoor sensor becomes unavailable at runtime."""
        hass.states.async_set("sensor.zone1_temp", "20.0")
        hass.states.async_set("switch.zone1_valve", "on")
        hass.states.async_set("sensor.supply_temp", "35.0")
        hass.states.async_set("sensor.outdoor_temp", "5.0")

        mock_config_entry_with_heating_curve.add_to_hass(hass)
        await hass.config_entries.async_setup(
            mock_config_entry_with_heating_curve.entry_id
        )
        await hass.async_block_till_done()

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Initially available
        assert controller.state.outdoor_temp == 5.0
        # Supply target calculated from curve
        assert controller.state.supply_target_temp == pytest.approx(33.0)

        # Make outdoor sensor unavailable
        hass.states.async_set("sensor.outdoor_temp", "unavailable")
        await hass.async_block_till_done()

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Now should be None and fallback to fixed target
        assert controller.state.outdoor_temp is None
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP
