"""Tests for disturbance recovery (perturbations mid-simulation)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import (
    ROOM_ARCHETYPES,
    assert_integral_bounded,
    assert_stable_temperature,
)

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
        """Window open for 10min at hour 4 + temp drop: recovers gracefully."""
        room = ROOM_ARCHETYPES["well_insulated"]

        # Window schedule: open from 4h to 4h10m (system still settling)
        window_start = 4 * 3600
        window_end = window_start + 600  # 10 minutes

        def window_schedule(t: float) -> bool:
            return window_start <= t < window_end

        harness, _controller, zid = make_single_zone_system(
            room,
            outdoor_temp=5.0,
            initial_temp=20.0,
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

        # No excessive overshoot during recovery: max 1.5°C above setpoint
        entries_after = log.zone_entries_after(zid, window_end)
        max_temp = max(e.room_temp for e in entries_after)
        assert max_temp <= 22.5, (
            f"Overshoot after window event: {max_temp:.2f}°C > 22.5°C"
        )

        # Integral should not spike during recovery
        assert_integral_bounded(log, zid)

    def test_setpoint_step_change(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Setpoint change 21->23 at hour 4: smooth approach, no oscillation."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=20.0, setpoint=21.0
        )

        def raise_setpoint(h: SimulationHarness) -> None:
            """Raise the setpoint mid-simulation."""
            h.controller.set_zone_setpoint(zid, 23.0)

        log = harness.run(
            48 * 3600,
            mutations=[(4 * 3600, raise_setpoint)],
        )

        # Should converge to the new setpoint
        assert_stable_temperature(log, zid, 23.0, tolerance=0.5, after_hours=36)

        # No oscillation: after settling, temperature should not swing
        # back and forth across setpoint with amplitude > 1°C
        entries_settled = log.zone_entries_after(zid, 36 * 3600)
        temps = [e.room_temp for e in entries_settled]
        temp_range = max(temps) - min(temps)
        assert temp_range <= 1.0, (
            f"Temperature oscillation {temp_range:.2f}°C after settling "
            f"(min={min(temps):.2f}, max={max(temps):.2f})"
        )

    def test_outdoor_temp_drop(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Outdoor temp 5->-5 at hour 6: adapts to new steady state."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=20.0, setpoint=21.0
        )

        def drop_outdoor(h: SimulationHarness) -> None:
            """Simulate a cold front."""
            h.outdoor_temp = -5.0
            h.rooms[zid].outdoor_temp = -5.0

        log = harness.run(
            48 * 3600,
            mutations=[(6 * 3600, drop_outdoor)],
        )

        # Should still maintain setpoint after adapting
        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=36)

        # Duty cycle should increase to compensate
        entries_after = log.zone_entries_after(zid, 36 * 3600)
        duties = [e.duty_cycle for e in entries_after]
        avg_duty = sum(duties) / len(duties)
        # With outdoor at -5°C: duty ≈ 0.56*(21+5)/50*100 = 29.1%
        # Before drop (outdoor 5°C): duty ≈ 0.56*16/50*100 = 17.9%
        assert avg_duty > 25.0, (
            f"Duty {avg_duty:.1f}% too low after outdoor drop to -5°C"
        )
