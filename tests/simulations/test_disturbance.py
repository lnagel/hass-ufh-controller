"""Tests for disturbance recovery (perturbations mid-simulation)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import ROOM_ARCHETYPES, assert_stable_temperature

if TYPE_CHECKING:
    from collections.abc import Callable

    from .harness import HeatingController, SimulationHarness


class TestDisturbanceRecovery:
    """Verify the controller recovers from mid-simulation perturbations."""

    def test_window_open_event(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Window open for 10min at hour 12 + temp drop: recovers gracefully."""
        room = ROOM_ARCHETYPES["well_insulated"]

        # Window schedule: open from 12h to 12h10m (after system has settled)
        window_start = 12 * 3600
        window_end = window_start + 600  # 10 minutes

        def window_schedule(t: float) -> bool:
            return window_start <= t < window_end

        harness, _controller, zid = make_single_zone_system(
            room,
            setpoint=21.0,
            window_schedules={"sim_zone": window_schedule},
        )

        def drop_temp(h: SimulationHarness) -> None:
            """Simulate heat loss from open window."""
            h.rooms[zid].temp -= 3.0

        log = harness.run(
            36 * 3600,
            mutations=[(window_start, drop_temp)],
        )

        # Should recover to setpoint after the disturbance
        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=24)

        # No extreme overshoot during recovery.
        # The proportional kick from a 3°C drop causes temporary overshoot
        # as the PID reacts aggressively to the large error.
        entries_after = log.zone_entries_after(zid, window_end)
        max_temp = max(e.room_temp for e in entries_after)
        assert max_temp <= 25.0, (
            f"Overshoot after window event: {max_temp:.2f}°C > 25.0°C"
        )

    def test_setpoint_step_change(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Setpoint change 21→23 at hour 12: smooth approach."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        def raise_setpoint(h: SimulationHarness) -> None:
            h.controller.set_zone_setpoint(zid, 23.0)

        log = harness.run(
            48 * 3600,
            mutations=[(12 * 3600, raise_setpoint)],
        )

        # Should converge to the new setpoint
        assert_stable_temperature(log, zid, 23.0, tolerance=0.5, after_hours=36)

    def test_outdoor_temp_drop(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Outdoor temp 5→-5 at hour 12: adapts to new steady state."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        def drop_outdoor(h: SimulationHarness) -> None:
            h.outdoor_temp = -5.0
            h.rooms[zid].outdoor_temp = -5.0

        log = harness.run(
            48 * 3600,
            mutations=[(12 * 3600, drop_outdoor)],
        )

        # Should still maintain setpoint after adapting
        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=36)

        # Duty cycle should increase to compensate
        entries_after = log.zone_entries_after(zid, 36 * 3600)
        duties = [e.duty_cycle for e in entries_after]
        avg_duty = sum(duties) / len(duties)
        # With outdoor at -5°C: duty ≈ 30*(21-(-5))/800*100 = 97.5%
        assert avg_duty > 50.0, (
            f"Duty {avg_duty:.1f}% too low after outdoor drop to -5°C"
        )
