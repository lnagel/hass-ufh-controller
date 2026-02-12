"""Tests for steady-state convergence and stability."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import ROOM_ARCHETYPES, assert_stable_temperature

if TYPE_CHECKING:
    from collections.abc import Callable

    from .conftest import SimulationHarness
    from .harness import HeatingController


class TestSteadyStateConvergence:
    """Verify the controller reaches and maintains target temperatures."""

    def test_reachable_setpoint(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Well-insulated room should settle within ±0.5°C of setpoint."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(24 * 3600)  # 24 hours

        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=16)

    def test_moderate_demand(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Moderate room settles with reasonable duty cycle."""
        room = ROOM_ARCHETYPES["moderate"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(48 * 3600)  # 48 hours

        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=24)

        # Duty cycle should be in a moderate range at steady state
        entries = log.zone_entries_after(zid, 24 * 3600)
        duties = [e.duty_cycle for e in entries]
        avg_duty = sum(duties) / len(duties)
        assert 40.0 <= avg_duty <= 95.0, f"Avg duty {avg_duty:.1f}% outside 40-95%"

    def test_unreachable_setpoint(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Borderline room at high setpoint should saturate at 100% duty."""
        room = ROOM_ARCHETYPES["borderline"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=28.0)

        log = harness.run(24 * 3600)  # 24 hours

        entries = log.zone_entries_after(zid, 12 * 3600)
        duties = [e.duty_cycle for e in entries]
        integrals = [e.integral for e in entries]

        # Integral should be clamped at max (100)
        assert max(integrals) == pytest.approx(100.0, abs=0.1)

        # Duty should be at or near 100%
        avg_duty = sum(duties) / len(duties)
        assert avg_duty >= 95.0, f"Avg duty {avg_duty:.1f}% should be ~100%"

        # Temp should be at the physical maximum the room can sustain
        # Steady state: T_room = T_outdoor + heating_power / heat_loss_coeff
        t_max = room.outdoor_temp + room.heating_power / room.heat_loss_coeff
        temps = [e.room_temp for e in entries]
        avg_temp = sum(temps) / len(temps)
        assert avg_temp <= t_max + 0.5, (
            f"Avg temp {avg_temp:.1f}°C exceeds physical max {t_max:.1f}°C"
        )

    def test_cold_start_no_overshoot(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Cold start should reach setpoint without excessive overshoot."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, setpoint=21.0, initial_temp=10.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        # Should eventually reach target
        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=16)

        # Check overshoot: max temp should not exceed setpoint + 3°C.
        # Cold starts accumulate integral during the long rise, causing
        # overshoot that the PID gradually corrects.
        entries = log.zone_entries(zid)
        max_temp = max(e.room_temp for e in entries)
        assert max_temp <= 24.0, f"Overshoot: max temp {max_temp:.2f}°C exceeds 24.0°C"

    @pytest.mark.parametrize(
        "room_key",
        ["well_insulated", "moderate"],
    )
    @pytest.mark.parametrize("ki", [0.0005, 0.001, 0.005])
    def test_convergence_parametrized(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
        room_key: str,
        ki: float,
    ) -> None:
        """Controller converges for various room types and ki values."""
        room = ROOM_ARCHETYPES[room_key]
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0, ki=ki)

        log = harness.run(48 * 3600)  # 48 hours

        # Should converge within ±1°C (broader tolerance for varied ki)
        assert_stable_temperature(log, zid, 21.0, tolerance=1.0, after_hours=24)
