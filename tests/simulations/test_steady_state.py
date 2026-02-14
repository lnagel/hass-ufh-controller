"""Tests for steady-state convergence and stability."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import (
    ROOM_ARCHETYPES,
    assert_heat_request_stable,
    assert_stable_temperature,
)

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
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=20.0, setpoint=21.0
        )

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
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=0.0, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(48 * 3600)  # 48 hours

        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=24)

        # Duty cycle should be near theoretical steady-state value
        # Steady-state: duty = heat_loss * (setpoint - outdoor) / power * 100
        # = 1.65 * 21 / 75 * 100 = 46.2%
        entries = log.zone_entries_after(zid, 24 * 3600)
        duties = [e.duty_cycle for e in entries]
        avg_duty = sum(duties) / len(duties)
        assert 35.0 <= avg_duty <= 55.0, f"Avg duty {avg_duty:.1f}% outside 35-55%"

    def test_unreachable_setpoint(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Borderline room at realistic setpoint should saturate at 100% duty."""
        room = ROOM_ARCHETYPES["borderline"]
        # Borderline max temp = 5 + 50/4.18 ≈ 17°C — cannot reach 21°C
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=15.0, setpoint=21.0
        )

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
        t_max = 5.0 + room.heating_power / room.heat_loss_coeff
        temps = [e.room_temp for e in entries]
        avg_temp = sum(temps) / len(temps)
        assert avg_temp <= t_max + 0.5, (
            f"Avg temp {avg_temp:.1f}°C exceeds physical max {t_max:.1f}°C"
        )

        # At 100% demand, heat request should be asserted for the vast majority
        # of time. It deasserts briefly near observation period boundaries when
        # remaining_duration drops below closing_warning_duration (boiler warning).
        heat_requests = [e.heat_request for e in entries if e.heat_request is not None]
        true_pct = sum(heat_requests) / len(heat_requests) * 100
        assert true_pct >= 90.0, (
            f"Heat request True only {true_pct:.0f}% of time at 100% demand "
            f"(expected >=90%)"
        )

    @pytest.mark.xfail(
        reason="Controller overshoots ~2.7°C from cold start due to integral "
        "accumulation during the long rise. Needs anti-windup improvement.",
        strict=True,
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
            room, outdoor_temp=5.0, initial_temp=10.0, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        # Should eventually reach target
        assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=16)

        # Check overshoot: max temp should not exceed setpoint + 1°C.
        entries = log.zone_entries(zid)
        max_temp = max(e.room_temp for e in entries)
        assert max_temp <= 22.0, f"Overshoot: max temp {max_temp:.2f}°C exceeds 22.0°C"

    @pytest.mark.parametrize(
        ("room_key", "outdoor_temp"),
        [
            ("well_insulated", 5.0),
            ("well_insulated", -10.0),
            ("well_insulated", -25.0),
            ("well_insulated", -30.0),
            ("moderate", 0.0),
            ("moderate", -15.0),
            ("moderate", -22.0),
            pytest.param(
                "leaky",
                -5.0,
                marks=pytest.mark.xfail(
                    reason="Permanent xfail: leaky room (high heat loss + high "
                    "heating power, short time constant) is outside the UFH "
                    "design envelope. Temperature swings are expected and "
                    "should not be 'fixed' in the controller.",
                    strict=True,
                ),
            ),
            pytest.param(
                "borderline",
                5.0,
                marks=pytest.mark.xfail(
                    reason="Permanent xfail: borderline room physically cannot "
                    "reach 21 °C (max ~17 °C). Controller correctly saturates "
                    "at 100% duty. This is a thermodynamic limit, not a bug.",
                    strict=True,
                ),
            ),
        ],
    )
    @pytest.mark.parametrize("ki", [0.0005, 0.001, 0.005])
    def test_convergence_parametrized(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
        room_key: str,
        outdoor_temp: float,
        ki: float,
    ) -> None:
        """Controller converges for various room types and ki values."""
        room = ROOM_ARCHETYPES[room_key]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=outdoor_temp, initial_temp=20.0, setpoint=21.0, ki=ki
        )

        log = harness.run(48 * 3600)  # 48 hours

        # Should converge within ±1°C (broader tolerance for varied ki)
        assert_stable_temperature(log, zid, 21.0, tolerance=1.0, after_hours=24)


class TestHeatRequestBehavior:
    """Verify heat request signal behavior at steady state."""

    def test_heat_request_chattering(
        self,
        make_single_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, str]
        ],
    ) -> None:
        """Heat request should not toggle more than 6 times/hour at steady state."""
        room = ROOM_ARCHETYPES["well_insulated"]
        harness, _controller, zid = make_single_zone_system(
            room, outdoor_temp=5.0, initial_temp=20.0, setpoint=21.0
        )

        log = harness.run(24 * 3600)  # 24 hours

        assert_heat_request_stable(log, zid, after_hours=16)
