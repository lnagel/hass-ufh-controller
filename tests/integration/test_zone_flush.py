"""Test flush circuit behavior."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ufh_controller.const import TimingParams, ValveState
from custom_components.ufh_controller.core.controller import ControllerState
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
    ZoneState,
    evaluate_zone,
)


class TestEvaluateZoneFlushCircuitPostDHW:
    """Test flush circuit behavior during post-DHW flush period."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create default timing params."""
        return TimingParams()

    def test_flush_during_post_dhw_turns_on(self, timing: TimingParams) -> None:
        """Flush circuit turns on during post-DHW flush period."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        controller = ControllerState(
            flush_enabled=True,
            flush_request=True,  # In post-DHW flush period
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.TURN_ON

    def test_flush_during_post_dhw_stays_on(self, timing: TimingParams) -> None:
        """Flush circuit stays on during post-DHW flush period."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.ON,
        )
        controller = ControllerState(
            flush_enabled=True,
            flush_request=True,  # In post-DHW flush period
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        assert result == ZoneAction.STAY_ON

    def test_flush_after_post_dhw_period_expired(self, timing: TimingParams) -> None:
        """Flush circuit follows normal logic after post-DHW period expires."""
        zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
            requested_duration=0.0,  # No quota
        )
        controller = ControllerState(
            flush_enabled=True,
            flush_request=False,  # Post-DHW period expired
            zones={"bathroom": zone},
        )
        result = evaluate_zone(zone, controller, timing)
        # Should follow normal logic (stays off with no quota)
        assert result == ZoneAction.STAY_OFF

    def test_flush_during_post_dhw_blocked_by_regular_valve_on(
        self, timing: TimingParams
    ) -> None:
        """Flush circuit blocked during post-DHW when regular valve is ON."""
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
            valve_state=ValveState.ON,  # Valve is actively running
            requested_duration=1000.0,
        )
        controller = ControllerState(
            flush_enabled=True,
            flush_request=False,
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )
        result = evaluate_zone(flush_zone, controller, timing)
        # Should fall through to normal quota logic (stays off with 0 quota)
        assert result == ZoneAction.STAY_OFF

    def test_flush_during_post_dhw_not_blocked_by_regular_demand_only(
        self, timing: TimingParams
    ) -> None:
        """Flush circuit NOT blocked during post-DHW when regular valve is OFF."""
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.OFF,
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
            valve_state=ValveState.OFF,  # Valve is OFF
            requested_duration=1000.0,  # Has demand but not running
        )
        controller = ControllerState(
            flush_enabled=True,
            flush_request=True,  # In post-DHW flush period
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )
        result = evaluate_zone(flush_zone, controller, timing)
        # Flush should turn on - regular valve is OFF
        assert result == ZoneAction.TURN_ON


class TestFlushCircuitScenarios:
    """Scenario tests for flush circuit behavior in real-world situations."""

    @pytest.fixture
    def timing(self) -> TimingParams:
        """Create default timing params."""
        return TimingParams()

    def test_flush_yields_to_regular_heating_during_post_dhw(
        self, timing: TimingParams
    ) -> None:
        """
        Scenario: Flush circuit yields when regular circuit starts heating.

        Timeline:
        1. DHW ends, post-DHW flush period starts
        2. Flush circuit is ON capturing residual heat
        3. Regular circuit turns ON (valid heat request, allowed since DHW ended)
        4. Flush circuit should turn OFF - regular heating takes priority

        This is expected behavior: regular heating demand takes priority over
        capturing residual waste heat. The regular zone has a valid heat request
        and should not be blocked by flush circuits.
        """
        flush_zone = ZoneState(
            zone_id="bathroom",
            circuit_type=CircuitType.FLUSH,
            valve_state=ValveState.ON,  # Was capturing heat
            requested_duration=0.0,  # No heating demand of its own
        )
        regular_zone = ZoneState(
            zone_id="living_room",
            circuit_type=CircuitType.REGULAR,
            enabled=True,
            valve_state=ValveState.ON,  # Started heating (valid request)
            requested_duration=1000.0,
        )
        controller = ControllerState(
            flush_enabled=True,
            flush_request=False,
            zones={"bathroom": flush_zone, "living_room": regular_zone},
        )

        result = evaluate_zone(flush_zone, controller, timing)

        # Flush circuit yields to regular heating - falls back to quota logic
        # With 0 quota, it turns off
        assert result == ZoneAction.TURN_OFF


class TestControllerStateFlushUntil:
    """Test ControllerState flush_until field."""

    def test_flush_until_default_none(self) -> None:
        """Test flush_until defaults to None."""
        controller = ControllerState()
        assert controller.flush_until is None

    def test_flush_until_can_be_set(self) -> None:
        """Test flush_until can be set to a datetime."""
        future_time = datetime.now(UTC) + timedelta(minutes=8)
        controller = ControllerState(flush_until=future_time)
        assert controller.flush_until == future_time

    def test_flush_request_default_false(self) -> None:
        """Test flush_request defaults to False."""
        controller = ControllerState()
        assert controller.flush_request is False

    def test_flush_request_can_be_set(self) -> None:
        """Test flush_request can be set to True."""
        controller = ControllerState(flush_request=True)
        assert controller.flush_request is True
