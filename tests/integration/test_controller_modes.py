"""Test heating controller mode evaluation and configuration."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    ValveState,
)
from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    HeatingController,
    ZoneConfig,
)
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
)


@pytest.fixture
def basic_config() -> ControllerConfig:
    """Create a basic controller configuration with two zones."""
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
            ZoneConfig(
                zone_id="bedroom",
                name="Bedroom",
                temp_sensor="sensor.bedroom_temp",
                valve_switch="switch.bedroom_valve",
            ),
        ],
    )


class TestEvaluateZonesAutoMode:
    """Test evaluate_zones in auto mode."""

    def test_zone_with_quota_turns_on(self, basic_config: ControllerConfig) -> None:
        """Test zone with remaining quota turns on."""
        controller = HeatingController(basic_config)

        # Set up zone with duty cycle and unused quota
        controller.update_zone_pid("living_room", 20.0, 60.0)
        controller.update_zone_historical(
            "living_room",
            period_state_avg=0.0,  # No usage yet
            open_state_avg=0.0,
            window_recently_open=False,
            elapsed_time=7200.0,  # Full observation period
        )

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.TURN_ON

    def test_disabled_zone_turns_off(self, basic_config: ControllerConfig) -> None:
        """Test disabled zone with unknown valve state emits TURN_OFF."""
        controller = HeatingController(basic_config)
        controller.set_zone_enabled("living_room", enabled=False)

        actions = controller.evaluate_zones()

        # Valve state is UNKNOWN by default, so actively turn off
        assert actions["living_room"] == ZoneAction.TURN_OFF

    def test_disabled_zone_confirmed_off_stays_off(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test disabled zone with confirmed OFF valve stays off."""
        controller = HeatingController(basic_config)
        controller.set_zone_enabled("living_room", enabled=False)
        zone_state = controller.get_zone_state("living_room")
        assert zone_state is not None
        zone_state.valve_state = ValveState.OFF

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_OFF


class TestEvaluateZonesAllOnMode:
    """Test evaluate_zones in all_on mode."""

    def test_all_valves_turn_on(self, basic_config: ControllerConfig) -> None:
        """Test all valves turn on in all_on mode."""
        controller = HeatingController(basic_config)
        controller.mode = "all_on"

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.TURN_ON
        assert actions["bedroom"] == ZoneAction.TURN_ON

    def test_valve_stays_on(self, basic_config: ControllerConfig) -> None:
        """Test valve that's already on stays on."""
        controller = HeatingController(basic_config)
        controller.mode = "all_on"

        # First evaluation turns on
        controller.evaluate_zones()

        # Second evaluation stays on
        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_ON


class TestEvaluateZonesAllOffMode:
    """Test evaluate_zones in all_off mode."""

    def test_all_valves_stay_off(self, basic_config: ControllerConfig) -> None:
        """Test all valves stay off in all_off mode."""
        controller = HeatingController(basic_config)
        controller.mode = "all_off"

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_OFF
        assert actions["bedroom"] == ZoneAction.STAY_OFF


class TestEvaluateZonesFlushMode:
    """Test evaluate_zones in flush mode."""

    def test_all_valves_turn_on(self, basic_config: ControllerConfig) -> None:
        """Test all valves turn on in flush mode."""
        controller = HeatingController(basic_config)
        controller.mode = "flush"

        actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.TURN_ON
        assert actions["bedroom"] == ZoneAction.TURN_ON


class TestEvaluateZonesDisabledMode:
    """Test evaluate_zones in disabled mode."""

    def test_valves_maintain_state(self, basic_config: ControllerConfig) -> None:
        """Test valves maintain state in disabled mode."""
        controller = HeatingController(basic_config)

        # Turn on a valve first
        controller.mode = "all_on"
        controller.evaluate_zones()

        # Switch to disabled
        controller.mode = "disabled"
        actions = controller.evaluate_zones()

        # Valves that were on stay on
        assert actions["living_room"] == ZoneAction.STAY_ON


class TestEvaluateZonesCycleMode:
    """Test evaluate_zones in cycle mode."""

    def test_cycle_mode_hour_0_all_off(self, basic_config: ControllerConfig) -> None:
        """Test all zones off during rest hour (hour 0)."""
        controller = HeatingController(basic_config)
        controller.mode = "cycle"

        with patch(
            "custom_components.ufh_controller.core.controller.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 0, 30, 0, tzinfo=UTC)
            mock_dt.UTC = UTC
            actions = controller.evaluate_zones()

        assert actions["living_room"] == ZoneAction.STAY_OFF
        assert actions["bedroom"] == ZoneAction.STAY_OFF

    def test_cycle_mode_first_zone_active(self, basic_config: ControllerConfig) -> None:
        """Test first zone active during hour 1."""
        controller = HeatingController(basic_config)
        controller.mode = "cycle"

        with patch(
            "custom_components.ufh_controller.core.controller.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 1, 30, 0, tzinfo=UTC)
            mock_dt.UTC = UTC
            actions = controller.evaluate_zones()

        # First zone should be on, second should be off
        assert actions["living_room"] == ZoneAction.TURN_ON
        assert actions["bedroom"] == ZoneAction.STAY_OFF

    def test_cycle_mode_second_zone_active(
        self, basic_config: ControllerConfig
    ) -> None:
        """Test second zone active during hour 2."""
        controller = HeatingController(basic_config)
        controller.mode = "cycle"

        with patch(
            "custom_components.ufh_controller.core.controller.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 2, 30, 0, tzinfo=UTC)
            mock_dt.UTC = UTC
            actions = controller.evaluate_zones()

        # Second zone should be on
        assert actions["living_room"] == ZoneAction.STAY_OFF
        assert actions["bedroom"] == ZoneAction.TURN_ON


class TestZoneConfig:
    """Test ZoneConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        config = ZoneConfig(
            zone_id="test",
            name="Test Zone",
            temp_sensor="sensor.test_temp",
            valve_switch="switch.test_valve",
        )
        assert config.circuit_type == CircuitType.REGULAR
        assert config.setpoint_min == DEFAULT_SETPOINT["min"]
        assert config.setpoint_max == DEFAULT_SETPOINT["max"]
        assert config.setpoint_default == DEFAULT_SETPOINT["default"]
        assert config.kp == DEFAULT_PID["kp"]
        assert config.ki == DEFAULT_PID["ki"]

    def test_flush_circuit(self) -> None:
        """Test flush circuit configuration."""
        config = ZoneConfig(
            zone_id="bathroom",
            name="Bathroom",
            temp_sensor="sensor.bathroom_temp",
            valve_switch="switch.bathroom_valve",
            circuit_type=CircuitType.FLUSH,
        )
        assert config.circuit_type == CircuitType.FLUSH


class TestControllerConfig:
    """Test ControllerConfig dataclass."""

    def test_minimal_config(self) -> None:
        """Test minimal configuration."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
        )
        assert config.dhw_active_entity is None
        assert config.summer_mode_entity is None
        assert len(config.zones) == 0

    def test_with_optional_entities(self) -> None:
        """Test configuration with optional entities."""
        config = ControllerConfig(
            controller_id="heating",
            name="Heating",
            dhw_active_entity="binary_sensor.dhw",
            summer_mode_entity="select.summer",
        )
        assert config.dhw_active_entity == "binary_sensor.dhw"
        assert config.summer_mode_entity == "select.summer"
