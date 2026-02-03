"""Integration tests for heating curve with outdoor temperature compensation."""

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
    SUBENTRY_TYPE_ZONE,
)
from tests.conftest import MOCK_ZONE_DATA


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
        options={"timing": DEFAULT_TIMING},
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
            "supply_target_temp": DEFAULT_SUPPLY_TARGET_TEMP,
        },
        options={"timing": DEFAULT_TIMING},
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


async def _setup_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    outdoor_temp: str | None = None,
) -> None:
    """Set up mock sensors and config entry."""
    hass.states.async_set("sensor.zone1_temp", "20.0")
    hass.states.async_set("switch.zone1_valve", "on")
    hass.states.async_set("sensor.supply_temp", "35.0")
    if outdoor_temp is not None:
        hass.states.async_set("sensor.outdoor_temp", outdoor_temp)

    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


class TestCoordinatorReadsOutdoorSensor:
    """Test coordinator reads outdoor sensor and populates controller state."""

    async def test_outdoor_temp_propagated_to_controller_state(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Coordinator reads outdoor sensor and populates controller state."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, "5.0")

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp == 5.0
        assert controller.state.supply_target_temp is not None

    @pytest.mark.parametrize(
        "invalid_state",
        ["unknown", "unavailable", "none"],
    )
    async def test_invalid_outdoor_sensor_state_returns_none(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
        invalid_state: str,
    ) -> None:
        """Invalid outdoor sensor states result in None outdoor temp."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, invalid_state)

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp is None
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP

    async def test_no_outdoor_entity_configured_uses_fallback(
        self,
        hass: HomeAssistant,
        mock_config_entry_no_heating_curve: MockConfigEntry,
    ) -> None:
        """Without outdoor entity configured, uses fixed fallback target."""
        await _setup_entry(hass, mock_config_entry_no_heating_curve)

        coordinator = mock_config_entry_no_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp is None
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP


class TestSupplyTargetSensorEntity:
    """Test supply target sensor entity creation and value."""

    async def test_sensor_created_with_outdoor_entity(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Supply target sensor is created when outdoor entity is configured."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, "5.0")

        state = hass.states.get(
            "sensor.test_controller_heating_curve_supply_target_temperature"
        )
        assert state is not None

    async def test_sensor_not_created_without_outdoor_entity(
        self,
        hass: HomeAssistant,
        mock_config_entry_no_heating_curve: MockConfigEntry,
    ) -> None:
        """Supply target sensor is NOT created without outdoor entity."""
        await _setup_entry(hass, mock_config_entry_no_heating_curve)

        state = hass.states.get(
            "sensor.test_controller_no_curve_supply_target_temperature"
        )
        assert state is None

    async def test_sensor_value_matches_coordinator_data(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Supply target sensor value comes from coordinator data."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, "2.5")

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        state = hass.states.get(
            "sensor.test_controller_heating_curve_supply_target_temperature"
        )
        assert state is not None
        controller_data = coordinator.data.get("controller", {})
        assert float(state.state) == controller_data.get("supply_target_temp")


class TestOutdoorSensorStateChanges:
    """Test behavior when outdoor sensor state changes at runtime."""

    async def test_outdoor_temp_change_updates_supply_target(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Changing outdoor temp triggers supply target recalculation."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, "15.0")

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        initial_target = controller.state.supply_target_temp

        # Change outdoor temp
        hass.states.async_set("sensor.outdoor_temp", "-10.0")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        new_target = controller.state.supply_target_temp
        assert new_target != initial_target

    async def test_outdoor_sensor_becomes_unavailable(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """When outdoor sensor becomes unavailable, falls back to fixed target."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, "5.0")

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp == 5.0
        assert controller.state.supply_target_temp != DEFAULT_SUPPLY_TARGET_TEMP

        # Make sensor unavailable
        hass.states.async_set("sensor.outdoor_temp", "unavailable")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert controller.state.outdoor_temp is None
        assert controller.state.supply_target_temp == DEFAULT_SUPPLY_TARGET_TEMP


class TestSupplyCoefficientIntegration:
    """Test supply coefficient uses dynamic supply target from heating curve."""

    async def test_supply_coefficient_uses_dynamic_target(
        self,
        hass: HomeAssistant,
        mock_config_entry_with_heating_curve: MockConfigEntry,
    ) -> None:
        """Supply coefficient calculation uses the dynamic supply target."""
        await _setup_entry(hass, mock_config_entry_with_heating_curve, "2.5")

        coordinator = mock_config_entry_with_heating_curve.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        zone_runtime = coordinator.controller.get_zone_runtime("zone1")
        assert zone_runtime is not None

        # Verify supply coefficient was calculated (not None)
        # The exact value depends on dynamic target, not a fixed 40°C
        assert zone_runtime.state.supply_coefficient is not None


class TestInvalidHeatingCurveConfig:
    """Test behavior with invalid heating curve configuration."""

    async def test_invalid_curve_uses_fallback(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Invalid curve (warm <= cold outdoor temps) uses fallback target."""
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
                "supply_target_temp": 42.0,
            },
            options={"timing": DEFAULT_TIMING},
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

        await _setup_entry(hass, entry, "5.0")

        coordinator = entry.runtime_data.coordinator
        controller = coordinator.controller

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Outdoor temp is read but invalid curve means fallback is used
        assert controller.state.outdoor_temp == 5.0
        assert controller.state.supply_target_temp == 42.0
