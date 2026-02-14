# Simulation Tests

The integration includes a physics-based simulation test suite that validates the
controller against a thermal room model over hours of simulated time. These tests
run the real `HeatingController` — the same code that runs in production — without
any Home Assistant dependencies, exercising PID control, quota scheduling, and
valve actuation under realistic conditions.

## How It Works

### Thermal Room Model

Each simulated room is a single-node lumped-capacitance model. At each 60-second
timestep the model computes heat gained from the floor circuit minus heat lost
through the building envelope, and updates the room temperature.

All thermal parameters are **per unit floor area** (W/m², kJ/(K·m²)). Area cancels
in the heat balance equation, so the model needs no explicit room size.

| Parameter | Unit | Meaning |
|---|---|---|
| Thermal mass | kJ/(K·m²) | Energy absorbed per degree per m² |
| Heat loss coefficient | W/(K·m²) | Heat loss rate to outdoors per m² |
| Heating power | W/m² | Heat delivered by the UFH circuit per m² |

A valve actuator model adds realistic delay: valves ramp open over 3 minutes and
close over 1.5 minutes. Heat is only delivered once the valve reaches 85% open.

### Room Archetypes

Four archetypes cover the range of real-world buildings. Parameters are derived
from EN 12831 (heat loss), ISO 13790 (thermal mass), and EN 1264 (UFH output).

| Archetype | Description | Time constant |
|---|---|---|
| **Well-insulated** | Passivhaus / current Nordic code | ~60 hours |
| **Moderate** | 1980s–2000s renovation | ~28 hours |
| **Leaky** | Pre-1960s uninsulated | ~13 hours |
| **Borderline** | Pre-1960s with undersized UFH | ~13 hours |

The **borderline** archetype deliberately cannot reach a 21 °C setpoint — it
stresses integral clamping and saturation behaviour. The **leaky** archetype has
high heating power but also high losses, creating fast temperature swings that
challenge the controller.

### Simulation Harness

The harness replaces the Home Assistant coordinator. It owns the time loop, feeds
sensor readings into the controller, executes returned valve actions against the
room models, and records a detailed log of every timestep.

Mid-simulation perturbations (window openings, setpoint changes, cold fronts) are
injected via **mutation callbacks**, keeping test setup declarative.

## What Is Tested

### Steady-State Convergence (`test_steady_state.py`)

Validates that the controller reaches and maintains target temperatures over 24–48
hours of simulated time.

- **Reachable setpoint** — well-insulated room settles within ±0.5 °C of 21 °C
- **Moderate demand** — higher heat-loss room converges with duty cycle 35–55%
- **Unreachable setpoint** — borderline room saturates at 100% duty; integral
  clamps at maximum; temperature reaches the physical limit
- **Cold start** — starting from 10 °C, the room reaches setpoint *(currently
  xfail: integral windup causes ~2.7 °C overshoot)*
- **Parameter sweep** — convergence verified across 4 archetypes at multiple
  outdoor temperatures × 3 Ki gain values (covering 30–95% duty range)
- **Heat request stability** — heat request signal does not chatter excessively
  (≤6 transitions/hour)

### Borderline Duty Cycles (`test_borderline_duty.py`)

The controller quantizes valve run times: if the computed duty is below ~7.5%,
the valve may skip a period entirely. These tests verify stable behaviour at
the boundary.

- **Just above threshold** — back-calculation keeps integral stable despite
  occasional short valve runs at period boundaries
- **Just below threshold** — valve mostly off, integral remains bounded, room
  stays warm
- **At threshold** — no integral drift or oscillation

### Anti-Windup (`test_anti_windup.py`)

The PID integral term is clamped to [0, 100] to prevent unbounded accumulation.

- **Clamp at maximum** — unreachable setpoint drives integral to exactly 100
- **Clamp at zero** — room above setpoint keeps integral at 0
- **Recovery from clamp** — after outdoor temperature warms and setpoint drops,
  integral decreases from the maximum
- **Back-calculation stability** — when actual valve delivery differs from PID
  output (under-delivery, over-delivery, sustained mismatch), the integral
  converges without drift

### Disturbance Recovery (`test_disturbance.py`)

Mid-simulation perturbations test the controller's ability to recover.

- **Window open** — 10-minute window event with 3 °C temperature drop; room
  recovers without excessive overshoot
- **Setpoint change** — raising setpoint from 21 °C to 23 °C; smooth approach
  to the new target
- **Outdoor temperature drop** — outdoor drops from 5 °C to −5 °C; duty cycle
  increases and room temperature is maintained

### Multi-Zone Interactions (`test_multi_zone.py`)

Multiple zones share the heating system and compete for quota within each
observation period.

- **Fair quota sharing** — three zones with different demands receive
  proportional heating time
- **Saturated zone isolation** — one zone at an unreachable setpoint does not
  starve neighbouring zones
- **DHW interruption** — a 20-minute domestic hot water priority event suspends
  zone heating; all zones recover afterwards

## Known Limitations (xfail Tests)

Seven tests are marked `xfail(strict=True)` — they pass only by *failing*, which
documents genuine controller limitations without breaking CI.

| Limitation | Affected tests | Root cause |
|---|---|---|
| Cold-start overshoot | 1 test | Integral windup during long rise from 10 °C |
| Leaky room oscillation | 3 tests (one per Ki) | Outside UFH design envelope; high power + fast thermal response |
| Borderline non-convergence | 3 tests (one per Ki) | Thermodynamic limit, not a bug; correctly saturates |

## Running the Tests

```bash
# Simulation tests only
uv run pytest tests/simulations/ -v

# Full test suite (includes simulations)
uv run pytest
```

The simulation tests are pure computation — no I/O, network, or Home Assistant
dependencies. The full suite of 47 tests runs in about two seconds.

## File Layout

```
tests/simulations/
├── conftest.py              # Room archetypes, factory fixtures, assertion helpers
├── room_model.py            # Lumped-capacitance thermal model
├── harness.py               # Simulation harness, log, and valve actuator model
├── test_steady_state.py     # Convergence, stability, heat request behaviour
├── test_borderline_duty.py  # Min-run-time quantization edge cases
├── test_anti_windup.py      # Integral clamping and back-calculation
├── test_disturbance.py      # Perturbation recovery
└── test_multi_zone.py       # Multi-zone quota, saturation, DHW priority
```
