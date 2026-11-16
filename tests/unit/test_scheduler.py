"""Unit tests for flow-rate-aware zone scheduling."""

from __future__ import annotations

from custom_components.ufh_controller.core.pid import PIDController
from custom_components.ufh_controller.core.scheduler import apply_flow_constraint
from custom_components.ufh_controller.core.zone import (
    ZoneAction,
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
)


def _make_runtime(
    zone_id: str,
    *,
    nominal_flow_rate: float | None = 2.0,
    requested_duration: float = 3600.0,
    used_duration: float = 0.0,
) -> ZoneRuntime:
    """Create a minimal ZoneRuntime for scheduler tests."""
    config = ZoneConfig(
        zone_id=zone_id,
        name=f"Zone {zone_id}",
        temp_sensor=f"sensor.{zone_id}_temp",
        valve_switch=f"switch.{zone_id}_valve",
        nominal_flow_rate=nominal_flow_rate,
    )
    pid = PIDController(kp=config.kp, ki=config.ki, kd=config.kd)
    state = ZoneState(zone_id=zone_id)
    state.requested_duration = requested_duration
    state.used_duration = used_duration
    return ZoneRuntime(config=config, pid=pid, state=state)


class TestMaxFlowEnforcement:
    """Tests for max-flow constraint in apply_flow_constraint."""

    def test_turn_on_without_flow_rate_passes_unconstrained(self) -> None:
        """Zones with no nominal_flow_rate are not constrained by max flow."""
        zones = {
            "z0": _make_runtime("z0", nominal_flow_rate=None),
            "z1": _make_runtime("z1", nominal_flow_rate=2.0),
        }
        actions = {"z0": ZoneAction.TURN_ON, "z1": ZoneAction.TURN_ON}

        result = apply_flow_constraint(
            actions, zones, optimal_flow_rate_min=None, optimal_flow_rate_max=2.0
        )

        # z0 passes through (no flow rate), z1 fits within budget
        assert result["z0"] == ZoneAction.TURN_ON
        assert result["z1"] == ZoneAction.TURN_ON

    def test_single_zone_exceeding_max_never_starved(self) -> None:
        """A single zone that exceeds max still turns on (never starve)."""
        zones = {"z0": _make_runtime("z0", nominal_flow_rate=5.0)}
        actions = {"z0": ZoneAction.TURN_ON}

        result = apply_flow_constraint(
            actions, zones, optimal_flow_rate_min=None, optimal_flow_rate_max=3.0
        )

        assert result["z0"] == ZoneAction.TURN_ON

    def test_second_zone_demoted_when_exceeding_max(self) -> None:
        """Second TURN_ON zone demoted when it would exceed max."""
        zones = {
            "z0": _make_runtime("z0", nominal_flow_rate=2.0, requested_duration=3600),
            "z1": _make_runtime("z1", nominal_flow_rate=2.0, requested_duration=1800),
        }
        actions = {"z0": ZoneAction.TURN_ON, "z1": ZoneAction.TURN_ON}

        result = apply_flow_constraint(
            actions, zones, optimal_flow_rate_min=None, optimal_flow_rate_max=3.0
        )

        # z0 has higher remaining quota, gets priority; z1 demoted
        assert result["z0"] == ZoneAction.TURN_ON
        assert result["z1"] == ZoneAction.STAY_OFF


class TestMinFlowEnforcement:
    """Tests for min-flow constraint in apply_flow_constraint."""

    def test_turn_on_demoted_when_below_min_flow(self) -> None:
        """Single TURN_ON below min flow is demoted to STAY_OFF."""
        zones = {"z0": _make_runtime("z0", nominal_flow_rate=2.0)}
        actions = {"z0": ZoneAction.TURN_ON}

        result = apply_flow_constraint(
            actions, zones, optimal_flow_rate_min=4.0, optimal_flow_rate_max=None
        )

        assert result["z0"] == ZoneAction.STAY_OFF

    def test_stay_on_preserved_when_below_min_flow(self) -> None:
        """STAY_ON zones are not demoted even if below min flow."""
        zones = {"z0": _make_runtime("z0", nominal_flow_rate=2.0)}
        actions = {"z0": ZoneAction.STAY_ON}

        result = apply_flow_constraint(
            actions, zones, optimal_flow_rate_min=4.0, optimal_flow_rate_max=None
        )

        assert result["z0"] == ZoneAction.STAY_ON

    def test_sufficient_flow_allows_turn_on(self) -> None:
        """TURN_ON allowed when total flow meets min threshold."""
        zones = {
            "z0": _make_runtime("z0", nominal_flow_rate=2.0),
            "z1": _make_runtime("z1", nominal_flow_rate=2.0),
        }
        actions = {"z0": ZoneAction.TURN_ON, "z1": ZoneAction.TURN_ON}

        result = apply_flow_constraint(
            actions, zones, optimal_flow_rate_min=4.0, optimal_flow_rate_max=None
        )

        assert result["z0"] == ZoneAction.TURN_ON
        assert result["z1"] == ZoneAction.TURN_ON
