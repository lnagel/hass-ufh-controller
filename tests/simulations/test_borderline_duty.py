"""Tests for borderline duty cycle behavior around min_run_time threshold."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import (
    ROOM_ARCHETYPES,
    assert_integral_bounded,
    assert_integral_stable,
    assert_no_rapid_cycling,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .conftest import SimulationHarness
    from .harness import HeatingController


class TestBorderlineDuty:
    """
    Verify behavior near the min_run_time quantization threshold.

    Steady-state formula: duty% = heat_loss * (setpoint - outdoor) / heating_power * 100

    With well_insulated (heat_loss=1.5 W/(K·m²), power=40 W/m²):
    - outdoor=18.5 → duty = 1.5*(21-18.5)/40*100 = 9.4%  (just above threshold)
    - outdoor=19.4 → duty = 1.5*(21-19.4)/40*100 = 6.0%  (just below threshold)
    - outdoor=19.0 → duty = 1.5*(21-19.0)/40*100 = 7.5%  (borderline)

    With default min_run_time=540s and observation_period=7200s:
    threshold ≈ 540/7200*100 = 7.5%
    """

    @pytest.mark.xfail(
        reason="Valve runs for only 300s at observation period boundary "
        "(min_run_time=540s). The controller does not enforce min_run_time "
        "across period transitions.",
        strict=True,
    )
    def test_duty_just_above_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Zone with ~9.4% duty should run each period, integral stable."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=18.5, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        # Integral should stay bounded
        assert_integral_bounded(log, zid)

        # Integral should stabilize (not drift monotonically)
        assert_integral_stable(log, zid, after_hours=8, max_drift=5.0)

        # Valve on-durations should respect min_run_time (skip init phase)
        assert_no_rapid_cycling(log, zid, min_on_duration=540.0, after_hours=4)

        # Valve should run in each observation period after settling.
        # Count distinct periods (2h each) with at least one valve-on step.
        entries = log.zone_entries_after(zid, 6 * 3600)
        observation_period = 7200
        periods_with_valve: set[int] = set()
        for e in entries:
            if e.valve_on:
                periods_with_valve.add(int(e.time) // observation_period)

        total_periods = len({int(e.time) // observation_period for e in entries})
        assert periods_with_valve, "Valve never opened despite duty above threshold"
        # Valve should fire in every period (at 9.4% duty, well above 7.5% threshold)
        assert len(periods_with_valve) == total_periods, (
            f"Valve ran in {len(periods_with_valve)}/{total_periods} periods "
            f"(expected every period at ~9.4% duty)"
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
            room, outdoor_temp=19.4, setpoint=21.0
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
            room, outdoor_temp=19.0, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        # Integral must remain bounded
        assert_integral_bounded(log, zid)

        # No excessive integral drift
        assert_integral_stable(log, zid, after_hours=8, max_drift=8.0)
