"""Fixtures and assertion helpers for simulation tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from custom_components.ufh_controller.const import TimingConfig
from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    HeatingController,
)
from custom_components.ufh_controller.core.zone import ZoneConfig

from .harness import SimulationHarness, SimulationLog
from .room_model import RoomModel

if TYPE_CHECKING:
    from collections.abc import Callable

NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Override root autouse fixtures (HA-dependent, would fail in simulations)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """No-op override — simulations don't use HA."""


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Allow lingering timers (no-op override)."""
    return True


@pytest.fixture(autouse=True)
def mock_recorder() -> None:
    """No-op override — simulations don't use the recorder."""


# ---------------------------------------------------------------------------
# Room archetypes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoomParams:
    """Per-m² building properties describing a room archetype."""

    thermal_mass: float  # kJ/(K·m²)
    heat_loss_coeff: float  # W/(K·m²)
    heating_power: float  # W/m²


ROOM_ARCHETYPES: dict[str, RoomParams] = {
    # Level 1: Passivhaus / current Nordic code (EN 12831, ISO 13790)
    # H_total = 55.9 W/K for 100 m², τ ≈ 60 h
    # Design load 23 W/m² at -20 °C; UFH 300 mm spacing, tile finish
    "well_insulated": RoomParams(
        thermal_mass=120.0,  # kJ/(K·m²) — ISO 13790 Light-Medium
        heat_loss_coeff=0.56,  # W/(K·m²) — EN 12831: 55.9 W/K ÷ 100 m²
        heating_power=30.0,  # W/m² — EN 1264: 300 mm spacing, supply 30-35 °C
    ),
    # Level 2: 1980s-2000s renovation
    # H_total = 164.8 W/K for 100 m², τ ≈ 28 h
    # Design load 68 W/m² at -20 °C; UFH 150-200 mm spacing, tile finish
    "moderate": RoomParams(
        thermal_mass=165.0,  # kJ/(K·m²) — ISO 13790 Medium
        heat_loss_coeff=1.65,  # W/(K·m²) — EN 12831: 164.8 W/K ÷ 100 m²
        heating_power=75.0,  # W/m² — EN 1264: 150 mm spacing, supply 40-45 °C
    ),
    # Level 3: Pre-1960s uninsulated
    # H_total = 418 W/K for 100 m², τ ≈ 13 h
    # Design load 171 W/m² at -20 °C (exceeds UFH max ~100 W/m² per EN 1264)
    # UFH 100 mm spacing, supply 42-50 °C; supplementary emitters needed
    "leaky": RoomParams(
        thermal_mass=200.0,  # kJ/(K·m²) — ISO 13790 Medium-Heavy
        heat_loss_coeff=4.18,  # W/(K·m²) — EN 12831: 418 W/K ÷ 100 m²
        heating_power=100.0,  # W/m² — EN 1264 max for occupied zones
    ),
    # Level 3 envelope with undersized UFH — cannot reach typical setpoints
    # T_max at outdoor 5 °C = 5 + 50/4.18 ≈ 17 °C (cannot reach 21 °C)
    "borderline": RoomParams(
        thermal_mass=200.0,  # kJ/(K·m²) — same as leaky
        heat_loss_coeff=4.18,  # W/(K·m²) — same as leaky
        heating_power=50.0,  # W/m² — undersized UFH in poorly insulated building
    ),
}


# ---------------------------------------------------------------------------
# Zone spec for multi-zone systems
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneSpec:
    """Specification for a zone in a multi-zone system."""

    zone_id: str
    room: RoomParams
    outdoor_temp: float
    initial_temp: float
    setpoint: float = 21.0
    kp: float = 50.0
    ki: float = 0.001


# ---------------------------------------------------------------------------
# Single-zone factory fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def make_single_zone_system() -> Callable[
    ..., tuple[SimulationHarness, HeatingController, str]
]:
    """Return a factory that creates a single-zone simulation system."""

    def _factory(
        room: RoomParams,
        *,
        outdoor_temp: float,
        initial_temp: float,
        setpoint: float = 21.0,
        kp: float = 50.0,
        ki: float = 0.001,
        observation_period: int = 7200,
        min_run_time: int = 540,
        temp_ema_time_constant: int = 0,
        dt: float = 60.0,
        dhw_schedule: Callable[[float], bool] | None = None,
        window_schedules: dict[str, Callable[[float], bool]] | None = None,
    ) -> tuple[SimulationHarness, HeatingController, str]:
        zone_id = "sim_zone"
        zone_config = ZoneConfig(
            zone_id=zone_id,
            name="Sim Zone",
            temp_sensor="sensor.sim_temp",
            valve_switch="switch.sim_valve",
            setpoint_default=setpoint,
            kp=kp,
            ki=ki,
            temp_ema_time_constant=temp_ema_time_constant,
        )
        config = ControllerConfig(
            controller_id="sim_controller",
            name="Sim Controller",
            timing=TimingConfig(
                observation_period=observation_period,
                min_run_time=min_run_time,
            ),
            zones=[zone_config],
        )
        controller = HeatingController(config, started_at=NOW)

        room_model = RoomModel(
            thermal_mass=room.thermal_mass,
            heat_loss_coeff=room.heat_loss_coeff,
            heating_power=room.heating_power,
            outdoor_temp=outdoor_temp,
            initial_temp=initial_temp,
        )

        harness = SimulationHarness(
            controller,
            {zone_id: room_model},
            dt=dt,
            outdoor_temp=outdoor_temp,
            dhw_schedule=dhw_schedule,
            window_schedules=window_schedules or {},
        )
        return harness, controller, zone_id

    return _factory


# ---------------------------------------------------------------------------
# Multi-zone factory fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def make_multi_zone_system() -> Callable[
    ..., tuple[SimulationHarness, HeatingController, list[str]]
]:
    """Return a factory that creates a multi-zone simulation system."""

    def _factory(
        specs: list[ZoneSpec],
        *,
        observation_period: int = 7200,
        min_run_time: int = 540,
        dt: float = 60.0,
        dhw_schedule: Callable[[float], bool] | None = None,
    ) -> tuple[SimulationHarness, HeatingController, list[str]]:
        zone_configs = []
        rooms: dict[str, RoomModel] = {}
        outdoor_temps: list[float] = []

        for spec in specs:
            zc = ZoneConfig(
                zone_id=spec.zone_id,
                name=f"Zone {spec.zone_id}",
                temp_sensor=f"sensor.{spec.zone_id}_temp",
                valve_switch=f"switch.{spec.zone_id}_valve",
                setpoint_default=spec.setpoint,
                kp=spec.kp,
                ki=spec.ki,
                temp_ema_time_constant=0,
            )
            zone_configs.append(zc)
            rooms[spec.zone_id] = RoomModel(
                thermal_mass=spec.room.thermal_mass,
                heat_loss_coeff=spec.room.heat_loss_coeff,
                heating_power=spec.room.heating_power,
                outdoor_temp=spec.outdoor_temp,
                initial_temp=spec.initial_temp,
            )
            outdoor_temps.append(spec.outdoor_temp)

        config = ControllerConfig(
            controller_id="sim_multi",
            name="Sim Multi Controller",
            timing=TimingConfig(
                observation_period=observation_period,
                min_run_time=min_run_time,
            ),
            zones=zone_configs,
        )
        controller = HeatingController(config, started_at=NOW)

        # Use average outdoor temp
        avg_outdoor = sum(outdoor_temps) / len(outdoor_temps)
        harness = SimulationHarness(
            controller,
            rooms,
            dt=dt,
            outdoor_temp=avg_outdoor,
            dhw_schedule=dhw_schedule,
        )
        zone_ids = [s.zone_id for s in specs]
        return harness, controller, zone_ids

    return _factory


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_stable_temperature(
    log: SimulationLog,
    zone_id: str,
    target: float,
    *,
    tolerance: float = 0.5,
    after_hours: float = 4,
) -> None:
    """Assert temperature settles within tolerance of target after settling time."""
    entries = log.zone_entries_after(zone_id, after_hours * 3600)
    assert entries, f"No entries for {zone_id} after {after_hours}h"
    temps = [e.room_temp for e in entries]
    avg = sum(temps) / len(temps)
    assert abs(avg - target) <= tolerance, (
        f"Avg temp {avg:.2f}°C not within ±{tolerance}°C of {target}°C "
        f"(min={min(temps):.2f}, max={max(temps):.2f})"
    )


def assert_integral_bounded(
    log: SimulationLog,
    zone_id: str,
    *,
    lo: float = 0.0,
    hi: float = 100.0,
) -> None:
    """Assert integral term stays within bounds for all entries."""
    entries = log.zone_entries(zone_id)
    for e in entries:
        assert lo <= e.integral <= hi, (
            f"Integral {e.integral:.2f} out of [{lo}, {hi}] at t={e.time:.0f}s"
        )


def assert_integral_stable(
    log: SimulationLog,
    zone_id: str,
    *,
    after_hours: float = 6,
    max_drift: float = 5.0,
) -> None:
    """Assert integral is not monotonically growing (converges)."""
    entries = log.zone_entries_after(zone_id, after_hours * 3600)
    if len(entries) < 10:
        return  # Not enough data

    integrals = [e.integral for e in entries]

    # Check that the range of integral values is bounded
    integral_range = max(integrals) - min(integrals)
    assert integral_range <= max_drift, (
        f"Integral range {integral_range:.2f} exceeds max drift {max_drift:.2f} "
        f"after {after_hours}h (min={min(integrals):.2f}, max={max(integrals):.2f})"
    )


def assert_heat_request_stable(
    log: SimulationLog,
    zone_id: str,
    *,
    after_hours: float = 6,
    max_transitions_per_hour: float = 6.0,
) -> None:
    """
    Assert heat request doesn't chatter excessively.

    Typical boilers tolerate 3-6 cycles/hour. Excessive heat request
    toggling indicates poor hysteresis or oscillating demand.
    """
    entries = log.zone_entries_after(zone_id, after_hours * 3600)
    if len(entries) < 2:
        return

    transitions = 0
    prev_hr = entries[0].heat_request
    for e in entries[1:]:
        if (
            e.heat_request is not None
            and prev_hr is not None
            and e.heat_request != prev_hr
        ):
            transitions += 1
        if e.heat_request is not None:
            prev_hr = e.heat_request

    duration_hours = (entries[-1].time - entries[0].time) / 3600
    if duration_hours < 0.5:
        return

    rate = transitions / duration_hours
    assert rate <= max_transitions_per_hour, (
        f"Heat request chattering: {rate:.1f} transitions/hour "
        f"(max {max_transitions_per_hour}) over {duration_hours:.1f}h "
        f"({transitions} total transitions)"
    )
