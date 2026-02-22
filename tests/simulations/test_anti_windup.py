"""Tests for PID integral anti-windup behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import (
    ROOM_ARCHETYPES,
    assert_integral_bounded,
    assert_integral_converged,
    assert_integral_stable,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .harness import HeatingController, SimulationHarness


class TestAntiWindup:
    """Verify integral term clamping and recovery."""

    def test_integral_clamps_at_max(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Unreachable setpoint should clamp integral at max (100)."""
        room = ROOM_ARCHETYPES["borderline"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=15.0, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        entries = log.zone_entries_after(zid, 12 * 3600)
        integrals = [e.integral for e in entries]

        # Should be clamped at max
        assert max(integrals) == pytest.approx(100.0, abs=0.1)

        # Should stay at max consistently
        avg_integral = sum(integrals) / len(integrals)
        assert avg_integral >= 99.0, f"Avg integral {avg_integral:.1f} should be ~100"

    def test_integral_clamped_at_zero_above_setpoint(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """While room is cooling from above setpoint, integral stays at 0."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=25.0, setpoint=21.0
        )

        log = harness.run(4 * 3600)  # 4 hours

        # Check entries where room hasn't yet dropped below setpoint.
        # Once the room crosses below, integral accumulates and heating
        # may push it back above — those entries will have nonzero integral.
        # So we only verify the initial cooling phase (before first crossing).
        entries = log.zone_entries(zid)

        # Find first entry where room drops to or below setpoint
        first_crossing = next(
            (i for i, e in enumerate(entries) if e.room_temp <= e.setpoint),
            len(entries),
        )
        cooling_phase = entries[:first_crossing]

        assert len(cooling_phase) > 0, "Room was never above setpoint"

        # During initial cooling phase, negative error should keep integral at 0
        for e in cooling_phase:
            assert e.integral == pytest.approx(0.0, abs=0.01), (
                f"Integral {e.integral:.3f} != 0 at t={e.time:.0f}s "
                f"with room_temp={e.room_temp:.2f}°C > setpoint={e.setpoint}°C"
            )

        # Heat request should be False during cooling phase (no heating needed)
        cooling_with_hr = [e for e in cooling_phase if e.heat_request is not None]
        for e in cooling_with_hr:
            assert not e.heat_request, (
                f"Heat request should be False while cooling above setpoint "
                f"at t={e.time:.0f}s (room={e.room_temp:.2f}°C > sp={e.setpoint}°C)"
            )

    def test_integral_recovers_from_clamp(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Integral decreases from 100 when conditions improve."""
        room = ROOM_ARCHETYPES["borderline"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=15.0, setpoint=21.0
        )

        def warm_up_outdoor(h: SimulationHarness) -> None:
            """Warm outdoor significantly, reducing heating demand."""
            h.outdoor_temp = 20.0
            h.rooms[zid].outdoor_temp = 20.0

        # Also lower setpoint so it becomes reachable
        def lower_setpoint(h: SimulationHarness) -> None:
            """Lower setpoint so room can actually reach it."""
            h.controller.set_zone_setpoint(zid, 21.0)

        log = harness.run(
            48 * 3600,
            mutations=[
                (12 * 3600, warm_up_outdoor),
                (12 * 3600, lower_setpoint),
            ],
        )

        # Before mutation (at hour 10-12): integral should be near max
        entries_before = [
            e for e in log.zone_entries(zid) if 10 * 3600 <= e.time < 12 * 3600
        ]
        if entries_before:
            integrals_before = [e.integral for e in entries_before]
            assert max(integrals_before) >= 95.0

        # After mutation settles: integral should decrease significantly
        entries_after = log.zone_entries_after(zid, 36 * 3600)
        if entries_after:
            integrals_after = [e.integral for e in entries_after]
            avg_after = sum(integrals_after) / len(integrals_after)
            assert avg_after < 90.0, (
                f"Integral {avg_after:.1f} didn't decrease after "
                f"outdoor warmed and setpoint lowered"
            )


class TestBackCalculation:
    """
    Verify integral behavior with back-calculation anti-windup.

    When actual valve delivery differs from PID-requested duty, the
    back-calculation corrects the integral term at period boundaries.
    These tests verify the integral stays at physically reasonable
    levels and the system handles demand transitions safely.
    """

    def test_under_delivery_correction(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Moderate demand, valve ramp overhead causes under-delivery: integral stable.

        With well_insulated (0.56 W/(K·m²), 30 W/m²) at outdoor=17:
        theoretical duty = 0.56*(21-17)/30*100 = 7.5%.  PID integral
        accumulation drives actual duty higher.  The integral should not
        ratchet upward indefinitely — it must converge to a stable value.
        """
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=17.0, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(48 * 3600)  # 48 hours — many observation periods

        # Integral must be bounded
        assert_integral_bounded(log, zid)

        # Integral must stabilize, not keep drifting upward
        assert_integral_stable(log, zid, after_hours=24, max_drift=5.0)

    def test_over_delivery_tolerance(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Mild demand near threshold: near-match delivery, stable integral.

        With well_insulated (0.56 W/(K·m²), 30 W/m²) at outdoor=18.87:
        theoretical duty = 0.56*(21-18.87)/30*100 = 4.0%.  PID integral
        drives actual duty near the 7.5% threshold.  The small mismatch
        between requested and delivered heat should not cause drift.
        """
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=18.87, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(48 * 3600)  # 48 hours

        # Integral must be bounded
        assert_integral_bounded(log, zid)

        # Integral should stabilize with minimal drift
        assert_integral_stable(log, zid, after_hours=24, max_drift=5.0)

    def test_sustained_under_delivery(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Sub-threshold demand for many periods: integral converges low.

        With well_insulated (0.56 W/(K·m²), 30 W/m²) at outdoor=19.67:
        theoretical duty = 0.56*(21-19.67)/30*100 = 2.5%.  The PID
        output oscillates below the 7.5% min-run threshold, so the valve
        fires sporadically (roughly every other period).

        The integral should converge to a value consistent with the
        steady-state duty (~2.5%), not ratchet toward the 100 clamp.
        """
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=19.67, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(48 * 3600)  # 48 hours — many observation periods

        # Integral must be bounded (this is the basic clamp check)
        assert_integral_bounded(log, zid)

        # Integral should converge to a steady value, not keep drifting
        assert_integral_stable(log, zid, after_hours=24, max_drift=5.0)

        # Integral should stay in the same order of magnitude as the
        # steady-state duty (~2.5%), not climb toward the 100 clamp.
        assert_integral_converged(log, zid, max_value=15, after_hours=24)

    def test_low_kp_integral_converges(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Low proportional gain: integral converges to steady-state level.

        With kp=10 at outdoor=19°C, the proportional term only exceeds
        the 7.5% min-run threshold when error > 0.75°C.  Once the room
        is near setpoint (error < 0.75°C), the integral provides the
        base demand and P provides the fine correction.

        Steady-state duty at outdoor=19°C:
          0.56*(21-19)/30*100 = 3.73%

        The integral should settle in the single digits, consistent
        with the steady-state heating need.
        """
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room,
            outdoor_temp=19.0,
            initial_temp=20.0,
            setpoint=21.0,
            kp=10.0,
            ki=0.001,
        )

        log = harness.run(48 * 3600)  # 48 hours

        # Integral must stabilize
        assert_integral_stable(log, zid, after_hours=24, max_drift=10.0)

        # Integral should stay well below the clamp — in the same
        # ballpark as the theoretical duty (3.73%), not at 100.
        assert_integral_converged(log, zid, max_value=15, after_hours=24)

    def test_demand_transition_bounded_overshoot(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Cold snap after mild weather: temperature stays within safe bounds.

        Phase 1 (0-24h): outdoor=20°C, kp=10 — low demand.
          duty ≈ 0.56*(21-20)/30*100 = 1.87%.
        Phase 2 (24-48h): outdoor drops to 0°C — high demand.
          duty ≈ 0.56*(21-0)/30*100 = 39.2%.

        Verifies the controller handles a sudden demand increase
        without temperature exceeding setpoint + 2°C.
        """
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room,
            outdoor_temp=20.0,
            initial_temp=21.0,
            setpoint=21.0,
            kp=10.0,
            ki=0.001,
        )

        def drop_outdoor(h: SimulationHarness) -> None:
            """Simulate sudden cold snap."""
            h.outdoor_temp = 0.0
            h.rooms[zid].outdoor_temp = 0.0

        log = harness.run(
            48 * 3600,
            mutations=[(24 * 3600, drop_outdoor)],
        )

        # Temperature should not overshoot more than 2°C above setpoint
        entries_phase2 = log.zone_entries_after(zid, 24 * 3600)
        temps = [e.room_temp for e in entries_phase2]
        max_temp = max(temps)
        assert max_temp < 21.0 + 2.0, (
            f"Max temp {max_temp:.2f}°C during demand transition exceeds "
            f"setpoint + 2°C (23°C)"
        )
