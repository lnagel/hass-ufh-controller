"""
Tests for flow control + back-calculation anti-windup interaction.

Scenario: 5 zones x 2 L/min each, boiler requires min 2 max 3 zones open.
Flow constraints create contention — zones compete for 3 simultaneous slots.
Deferred zones accumulate PID integral without receiving heat.
Back-calculation should correct their integrals at period boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import (
    ROOM_ARCHETYPES,
    ZoneSpec,
    assert_integral_bounded,
    assert_integral_converged,
    assert_integral_stable,
    assert_stable_temperature,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .conftest import SimulationHarness
    from .harness import HeatingController

WELL_INSULATED = ROOM_ARCHETYPES["well_insulated"]


def _make_flow_specs(
    outdoor_temps: list[float],
    *,
    kp: float = 30.0,
    setpoint: float = 21.0,
    flow_rate: float = 2.0,
) -> list[ZoneSpec]:
    """Build 5-zone specs with equal flow rates and varying outdoor temps."""
    return [
        ZoneSpec(
            zone_id=f"z{i}",
            room=WELL_INSULATED,
            outdoor_temp=t_out,
            initial_temp=t_out + 2.0,
            setpoint=setpoint,
            kp=kp,
            ki=0.001,
            nominal_flow_rate=flow_rate,
        )
        for i, t_out in enumerate(outdoor_temps)
    ]


class TestFlowControl:
    """Verify flow-constrained scheduling with back-calculation anti-windup."""

    def test_flow_limited_zones_reach_setpoint(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """All 5 zones reach setpoint despite only 3 firing at a time."""
        specs = _make_flow_specs([5.0, 10.0, 12.0, 15.0, 18.0])
        harness, _controller, zone_ids = make_multi_zone_system(
            specs,
            optimal_flow_rate_min=4.0,
            optimal_flow_rate_max=6.0,
        )

        log = harness.run(72 * 3600)

        for zid in zone_ids:
            assert_stable_temperature(log, zid, 21.0, tolerance=1.0, after_hours=48)
            assert_integral_bounded(log, zid, lo=0.0, hi=100.0)

    def test_flow_limited_integral_stays_reasonable(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """Integral doesn't ratchet to clamp for deferred zones (uniform demand)."""
        # All zones identical outdoor temp → equal theoretical duty ~11.2%
        specs = _make_flow_specs([15.0, 15.0, 15.0, 15.0, 15.0])
        harness, _controller, zone_ids = make_multi_zone_system(
            specs,
            optimal_flow_rate_min=4.0,
            optimal_flow_rate_max=6.0,
        )

        log = harness.run(72 * 3600)

        for zid in zone_ids:
            assert_integral_converged(log, zid, max_value=30.0, after_hours=36)
            assert_integral_stable(log, zid, after_hours=36, max_drift=10.0)

    def test_flow_limited_fair_allocation(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """Zones with higher demand get proportionally more runtime."""
        outdoor_temps = [0.0, 5.0, 10.0, 15.0, 18.0]
        specs = _make_flow_specs(outdoor_temps)
        harness, _controller, zone_ids = make_multi_zone_system(
            specs,
            optimal_flow_rate_min=4.0,
            optimal_flow_rate_max=6.0,
        )

        log = harness.run(72 * 3600)

        # Collect total used_duration per zone (sum of max per observation period)
        used_durations: dict[str, float] = {}
        for zid in zone_ids:
            entries = log.zone_entries_after(zid, 24 * 3600)
            used_durations[zid] = sum(e.used_duration for e in entries)

        # Highest demand zone (outdoor=0) should have most used_duration
        assert used_durations["z0"] > used_durations["z4"], (
            f"Highest demand zone z0 ({used_durations['z0']:.0f}s) should "
            f"exceed lowest demand z4 ({used_durations['z4']:.0f}s)"
        )

        # Temperature ordering: colder outdoor → lower room temp (harder to heat)
        avg_temps: dict[str, float] = {}
        for zid in zone_ids:
            entries = log.zone_entries_after(zid, 48 * 3600)
            avg_temps[zid] = sum(e.room_temp for e in entries) / len(entries)

        # All zones should be within reasonable range of setpoint
        for zid in zone_ids:
            assert abs(avg_temps[zid] - 21.0) <= 1.5, (
                f"{zid}: avg temp {avg_temps[zid]:.2f}°C too far from 21°C"
            )

    def test_heat_request_requires_min_flow(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """
        Single high-demand zone deferred by min-flow; heat never fires.

        With min-flow enforcement in apply_flow_constraint, a single zone
        wanting TURN_ON (2 L/min < min_flow 4 L/min) gets demoted to
        STAY_OFF. The valve never opens, so no flow occurs and heat_request
        stays False.
        """
        # One high-demand zone, four low-demand zones (outdoor >= setpoint)
        specs = _make_flow_specs([0.0, 22.0, 22.0, 22.0, 22.0])
        harness, _controller, _zone_ids = make_multi_zone_system(
            specs,
            optimal_flow_rate_min=4.0,
            optimal_flow_rate_max=6.0,
        )

        log = harness.run(24 * 3600)

        # z0 valve should never be on — deferred by min-flow constraint
        z0_entries = log.zone_entries_after("z0", 1 * 3600)
        z0_valve_on = [e for e in z0_entries if e.valve_on]
        assert len(z0_valve_on) == 0, (
            f"z0 valve was on {len(z0_valve_on)} times — "
            "min-flow should prevent opening"
        )

        # z0 should never have flow
        z0_flow = [e for e in z0_entries if e.flow]
        assert len(z0_flow) == 0, (
            f"z0 had flow {len(z0_flow)} times — should be deferred"
        )

        # heat_request should never be True (no zones flowing)
        heat_by_time: dict[float, bool | None] = {}
        for e in log.entries:
            heat_by_time[e.time] = e.heat_request
        heat_true_count = sum(1 for hr in heat_by_time.values() if hr is True)
        assert heat_true_count == 0, (
            f"heat_request was True {heat_true_count} times — "
            "should never fire with no flow"
        )

    def test_single_demand_zone_deferred_by_min_flow(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """
        Single demanding zone deferred by min-flow: back-calc keeps integral bounded.

        When only 1 zone needs heat (outdoor=19°C, setpoint=21°C) and 4
        zones are warm (outdoor=22°C), total prospective flow (2 L/min) <
        min_flow (4 L/min). The TURN_ON is demoted to STAY_OFF by
        apply_flow_constraint. The valve stays closed, used_duration=0.

        Back-calculation at period end sees u_actual=0 vs u_commanded≈60%
        and corrects the integral downward (~-14.4 per period), preventing
        ratcheting to 100.

        Without back-calc the integral would ratchet to the clamp in ~7
        periods. With it, the integral stays well bounded.
        """
        # 1 zone at outdoor=19 (moderate demand), 4 at outdoor=22 (no demand)
        specs = _make_flow_specs([19.0, 22.0, 22.0, 22.0, 22.0], setpoint=21.0)
        harness, _controller, _zone_ids = make_multi_zone_system(
            specs,
            optimal_flow_rate_min=4.0,
            optimal_flow_rate_max=6.0,
        )

        log = harness.run(48 * 3600)

        # Integral stays well below clamp — back-calc prevents ratcheting
        assert_integral_converged(log, "z0", max_value=20.0, after_hours=24)
        assert_integral_stable(log, "z0", after_hours=24, max_drift=20.0)

        # Zone temp should be near outdoor (~19°C) — no heat delivered
        z0_entries = log.zone_entries_after("z0", 24 * 3600)
        z0_temps = [e.room_temp for e in z0_entries]
        z0_avg_temp = sum(z0_temps) / len(z0_temps)
        assert z0_avg_temp < 20.5, (
            f"Zone should stay near outdoor temp, got avg {z0_avg_temp:.1f}°C"
        )

        # Zone should never have flow — min-flow enforcement
        z0_flow = [e for e in z0_entries if e.flow]
        assert len(z0_flow) == 0, (
            f"z0 had flow {len(z0_flow)} times — should be deferred"
        )
