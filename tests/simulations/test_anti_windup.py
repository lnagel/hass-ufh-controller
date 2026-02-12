"""Tests for PID integral anti-windup behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import ROOM_ARCHETYPES, RoomParams, assert_integral_bounded

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
        harness, _controller, zid = make_single_zone_system(room, setpoint=28.0)

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

    def test_integral_stable_below_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Duty below min_run_time for many periods: integral converges."""
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=19.4,  # ~6% duty, below 7.5% threshold
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(24 * 3600)  # 24 hours

        # Integral should stay bounded
        assert_integral_bounded(log, zid)

    def test_integral_recovers_from_clamp(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Integral decreases from 100 when conditions improve."""
        room = ROOM_ARCHETYPES["borderline"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=28.0)

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
