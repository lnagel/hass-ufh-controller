"""Tests for borderline duty cycle behavior around min_run_time threshold."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import (
    RoomParams,
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

    With well_insulated (heat_loss=30, power=800):
    - outdoor=18.5 → duty = 30*(21-18.5)/800*100 = 9.4%  (just above threshold)
    - outdoor=19.4 → duty = 30*(21-19.4)/800*100 = 6.0%  (just below threshold)
    - outdoor=19.0 → duty = 30*(21-19.0)/800*100 = 7.5%  (borderline)

    With default min_run_time=540s and observation_period=7200s:
    threshold ≈ 540/7200*100 = 7.5%
    """

    def test_duty_just_above_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Zone with ~9.4% duty should run each period, integral stable."""
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=18.5,
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(24 * 3600)  # 24 hours

        # Integral should stay bounded
        assert_integral_bounded(log, zid)

        # Integral should stabilize (not drift monotonically)
        assert_integral_stable(log, zid, after_hours=8, max_drift=5.0)

        # Valve should actually run in at least some periods after settling
        entries = log.zone_entries_after(zid, 6 * 3600)
        valve_on_count = sum(1 for e in entries if e.valve_on)
        assert valve_on_count > 0, "Valve never opened despite duty above threshold"

    def test_duty_just_below_threshold(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Zone with ~6% duty: valve mostly off, integral bounded."""
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=19.4,
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(24 * 3600)  # 24 hours

        # Integral should stay bounded
        assert_integral_bounded(log, zid)

        # Temperature should still be reasonable (slightly below setpoint is OK)
        entries = log.zone_entries_after(zid, 12 * 3600)
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
        room = RoomParams(
            thermal_mass=50,
            heat_loss_coeff=30,
            heating_power=800,
            outdoor_temp=19.0,
        )
        harness, _controller, zid = make_single_zone_system(room, setpoint=21.0)

        log = harness.run(24 * 3600)  # 24 hours

        # Integral must remain bounded
        assert_integral_bounded(log, zid)

        # No excessive integral drift
        assert_integral_stable(log, zid, after_hours=8, max_drift=8.0)
