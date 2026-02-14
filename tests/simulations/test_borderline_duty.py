"""Tests for borderline duty cycle behavior around min_run_time threshold."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import (
    ROOM_ARCHETYPES,
    assert_integral_bounded,
    assert_integral_stable,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .conftest import SimulationHarness
    from .harness import HeatingController


class TestBorderlineDuty:
    """
    Verify behavior near the min_run_time quantization threshold.

    Steady-state formula: duty% = heat_loss * (setpoint - outdoor) / heating_power * 100

    With well_insulated (heat_loss=0.56 W/(K·m²), power=30 W/m²):
    - outdoor=18.5 → duty = 0.56*(21-18.5)/30*100 = 4.7%  (below threshold)
    - outdoor=19.4 → duty = 0.56*(21-19.4)/30*100 = 3.0%  (well below threshold)
    - outdoor=19.0 → duty = 0.56*(21-19.0)/30*100 = 3.7%  (below threshold)

    These theoretical steady-state values are all below the 7.5% threshold,
    but PID integral accumulation drives the actual duty cycle higher than
    the instantaneous proportional-only estimate.

    With default min_run_time=540s and observation_period=7200s:
    threshold ≈ 540/7200*100 = 7.5%
    """

    def test_duty_just_above_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """
        Above-threshold duty: back-calculation keeps integral stable.

        At this outdoor temp the PID settles to a duty just above the 7.5%
        threshold.  Occasional short valve runs near observation period
        boundaries cause under-delivery.  Back-calculation should correct
        the integral so it doesn't drift upward over many periods.
        """
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=18.5, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        # Integral should stay bounded
        assert_integral_bounded(log, zid)

        # KEY: integral must stabilize despite under-delivery from short runs
        assert_integral_stable(log, zid, after_hours=8, max_drift=5.0)

        # Valve should fire in a majority of observation periods after settling.
        # It won't necessarily fire every period at this low duty, but it
        # should be active regularly — not starved by integral drift.
        entries = log.zone_entries_after(zid, 6 * 3600)
        observation_period = 7200
        periods_with_valve: set[int] = set()
        for e in entries:
            if e.valve_on:
                periods_with_valve.add(int(e.time) // observation_period)

        total_periods = len({int(e.time) // observation_period for e in entries})
        assert periods_with_valve, "Valve never opened despite duty above threshold"
        assert len(periods_with_valve) >= total_periods // 2, (
            f"Valve ran in only {len(periods_with_valve)}/{total_periods} periods "
            f"(expected at least half)"
        )

    def test_duty_just_below_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Zone with ~6% duty: valve mostly off, integral doesn't ratchet."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=19.4, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(48 * 3600)  # 48 hours — many observation periods

        # Integral should stay bounded
        assert_integral_bounded(log, zid)

        # Integral should not ratchet upward unboundedly — must converge
        assert_integral_stable(log, zid, after_hours=24, max_drift=5.0)

        # Temperature should still be reasonable (slightly below setpoint is OK)
        entries = log.zone_entries_after(zid, 24 * 3600)
        temps = [e.room_temp for e in entries]
        avg_temp = sum(temps) / len(temps)
        # Room should be close-ish to setpoint even without running the valve
        # because outdoor is mild (19.4°C) and there's passive heat
        assert avg_temp >= 19.0, f"Avg temp {avg_temp:.1f}°C too low"

    def test_duty_oscillates_around_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Zone at ~7.5% duty: borderline, stable without integral drift."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=19.0, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        # Integral must remain bounded
        assert_integral_bounded(log, zid)

        # No excessive integral drift
        assert_integral_stable(log, zid, after_hours=8, max_drift=8.0)
