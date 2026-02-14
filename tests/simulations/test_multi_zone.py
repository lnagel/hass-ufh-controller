"""Tests for multi-zone interactions and quota sharing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import ROOM_ARCHETYPES, ZoneSpec, assert_stable_temperature

if TYPE_CHECKING:
    from collections.abc import Callable

    from .conftest import SimulationHarness
    from .harness import HeatingController


class TestMultiZone:
    """Verify inter-zone quota scheduling and fair sharing."""

    def test_fair_quota_sharing(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """Three zones with different demands get proportional quota."""
        specs = [
            ZoneSpec(
                zone_id="z1",
                room=ROOM_ARCHETYPES["well_insulated"],
                outdoor_temp=5.0,
                initial_temp=20.0,
                setpoint=21.0,
            ),
            ZoneSpec(
                zone_id="z2",
                room=ROOM_ARCHETYPES["moderate"],
                outdoor_temp=0.0,
                initial_temp=20.0,
                setpoint=21.0,
            ),
            ZoneSpec(
                zone_id="z3",
                room=ROOM_ARCHETYPES["well_insulated"],
                outdoor_temp=5.0,
                initial_temp=21.0,
                setpoint=22.0,
            ),
        ]
        harness, _controller, zone_ids = make_multi_zone_system(specs)

        log = harness.run(48 * 3600)

        # All zones should maintain reasonable temperatures
        for zid in zone_ids:
            entries = log.zone_entries_after(zid, 24 * 3600)
            temps = [e.room_temp for e in entries]
            avg = sum(temps) / len(temps)
            setpoint = entries[0].setpoint
            assert abs(avg - setpoint) <= 1.5, (
                f"{zid}: avg temp {avg:.1f}°C too far from setpoint {setpoint}°C"
            )

        # Zone with higher demand (moderate) should have higher duty
        z1_entries = log.zone_entries_after("z1", 24 * 3600)
        z2_entries = log.zone_entries_after("z2", 24 * 3600)
        z1_duty = sum(e.duty_cycle for e in z1_entries) / len(z1_entries)
        z2_duty = sum(e.duty_cycle for e in z2_entries) / len(z2_entries)
        assert z2_duty > z1_duty, (
            f"Moderate room duty {z2_duty:.1f}% should exceed "
            f"well-insulated {z1_duty:.1f}%"
        )

        # used_duration should be proportional to duty cycle.
        # Sample at observation period boundaries (when used_duration resets).
        # Compare the ratio of max used_duration per period.
        z1_max_used = max(e.used_duration for e in z1_entries)
        z2_max_used = max(e.used_duration for e in z2_entries)
        if z1_max_used > 0:
            ratio = z2_max_used / z1_max_used
            assert ratio > 1.0, (
                f"Moderate zone used_duration ({z2_max_used:.0f}s) should exceed "
                f"well-insulated ({z1_max_used:.0f}s)"
            )

    def test_saturated_zone_no_impact(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """One saturated zone should not starve normal zones."""
        specs = [
            ZoneSpec(
                zone_id="z_sat",
                room=ROOM_ARCHETYPES["borderline"],
                outdoor_temp=5.0,
                initial_temp=15.0,
                setpoint=28.0,  # Unreachable → saturated
            ),
            ZoneSpec(
                zone_id="z_normal1",
                room=ROOM_ARCHETYPES["well_insulated"],
                outdoor_temp=5.0,
                initial_temp=20.0,
                setpoint=21.0,
            ),
            ZoneSpec(
                zone_id="z_normal2",
                room=ROOM_ARCHETYPES["well_insulated"],
                outdoor_temp=5.0,
                initial_temp=20.0,
                setpoint=21.0,
            ),
        ]
        harness, _controller, _zone_ids = make_multi_zone_system(specs)

        log = harness.run(48 * 3600)

        # Normal zones should still reach their setpoints
        for zid in ["z_normal1", "z_normal2"]:
            assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=24)

        # Saturated zone should be at 100% duty
        sat_entries = log.zone_entries_after("z_sat", 12 * 3600)
        sat_duties = [e.duty_cycle for e in sat_entries]
        avg_sat = sum(sat_duties) / len(sat_duties)
        assert avg_sat >= 95.0, f"Saturated zone duty {avg_sat:.1f}% < 95%"

    def test_dhw_interruption(
        self,
        make_multi_zone_system: Callable[
            ..., tuple[SimulationHarness, HeatingController, list[str]]
        ],
    ) -> None:
        """DHW active for 20min mid-period: no new valves open, zones recover."""
        specs = [
            ZoneSpec(
                zone_id="z1",
                room=ROOM_ARCHETYPES["well_insulated"],
                outdoor_temp=5.0,
                initial_temp=20.0,
                setpoint=21.0,
            ),
            ZoneSpec(
                zone_id="z2",
                room=ROOM_ARCHETYPES["moderate"],
                outdoor_temp=0.0,
                initial_temp=20.0,
                setpoint=21.0,
            ),
        ]

        # DHW active from hour 18 to hour 18:20
        dhw_start = 18 * 3600
        dhw_end = dhw_start + 1200  # 20 minutes

        def dhw_schedule(t: float) -> bool:
            return dhw_start <= t < dhw_end

        harness, _controller, zone_ids = make_multi_zone_system(
            specs, dhw_schedule=dhw_schedule
        )

        log = harness.run(48 * 3600)

        # During DHW the boiler heats the tank, not the UFH manifold.
        # Already-open valves are harmless (no hot supply water flowing).
        # The controller should prevent NEW valve activations during DHW.
        for zid in zone_ids:
            dhw_entries = log.zone_entries_after(zid, dhw_start)
            dhw_entries = [e for e in dhw_entries if e.time < dhw_end]
            # Check no valve that was OFF turns ON during DHW
            prev_on = None
            for e in dhw_entries:
                if prev_on is False and e.valve_on:
                    msg = (
                        f"{zid}: valve turned ON at t={e.time:.0f}s during DHW "
                        f"(controller should not start new zones)"
                    )
                    raise AssertionError(msg)
                prev_on = e.valve_on

        # Both zones should recover to setpoint after DHW
        for zid in zone_ids:
            assert_stable_temperature(log, zid, 21.0, tolerance=0.5, after_hours=30)
