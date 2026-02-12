"""Tests for PID integral anti-windup behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import (
    ROOM_ARCHETYPES,
    RoomParams,
    assert_integral_bounded,
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
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

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
            room, setpoint=21.0, initial_temp=25.0
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

    def test_integral_recovers_from_clamp(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Integral decreases from 100 when conditions improve."""
        room = ROOM_ARCHETYPES["borderline"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

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
    Verify back-calculation anti-windup per plan.

    When actual valve delivery differs from PID-requested duty, the
    integral term should adjust to prevent ratcheting.  These tests
    will fail if the controller lacks a back-calculation mechanism.
    """

    def test_under_delivery_correction(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Duty=15%, valve ramp overhead causes under-delivery: integral stable.

        At 15% duty the valve is requested for ~1080s per 7200s period.
        Valve ramp (180s to reach 85% open) means actual heat delivery is
        less than requested.  The integral should not ratchet upward
        indefinitely — it must converge to a stable value.
        """
        # 30*(21-17)/800*100 = 15%
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=17.0,
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

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
        Duty=8%, valve runs for min_run_time (7.5%): near-match, stable.

        At 8% duty the requested duration (576s) is just above min_run_time
        (540s).  The valve runs for min_run_time, delivering ~7.5%.
        The 0.5% mismatch is small — integral should stay roughly stable.
        """
        # 30*(21-18.87)/800*100 ≈ 8%
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=18.87,
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

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
        Duty=5% (below threshold) for many periods: integral converges.

        At 5% duty the requested duration (360s) is below min_run_time
        (540s), so the valve never fires.  Without back-calculation the
        integral will ratchet to 100%.  With proper anti-windup the
        integral should converge to a steady value that reflects the
        fact that no heat can be delivered below the threshold.
        """
        # 30*(21-19.67)/800*100 ≈ 5%
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=19.67,
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(48 * 3600)  # 48 hours — many observation periods

        # Integral must be bounded (this is the basic clamp check)
        assert_integral_bounded(log, zid)

        # KEY CHECK: Integral should converge to a steady value, not
        # keep growing to the clamp.  If the integral grows monotonically
        # to 100, the controller lacks back-calculation anti-windup.
        assert_integral_stable(log, zid, after_hours=24, max_drift=5.0)
