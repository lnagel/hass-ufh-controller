# Simulation Tests

The integration includes a physics-based simulation test suite that validates the controller against a thermal room model over hours of simulated time. These tests run the real `HeatingController` (the same code that runs in production) without any Home Assistant dependencies, exercising PID control, quota scheduling, and valve actuation in realistic conditions.

## Thermal Model

Each simulated room is a lumped-capacitance model with four parameters:

| Parameter | Unit | Meaning |
|---|---|---|
| Thermal mass | kJ/K | How much energy the room absorbs per degree |
| Heat loss coefficient | W/K | Rate of heat loss to outdoors |
| Heating power | W | Heat delivered by the underfloor circuit |
| Outdoor temperature | C | Ambient temperature outside |

At each 60-second timestep, the model computes heat gained from the floor circuit minus heat lost through the envelope, and updates the room temperature accordingly. A valve actuator model adds realistic delay: valves ramp open over 3 minutes and close over 1.5 minutes, with heat delivery only once the valve is sufficiently open.

## Room Archetypes

Four room types cover the range of real-world conditions:

| Archetype | Description | Steady-state max temp |
|---|---|---|
| Well-insulated | Low heat loss, mild outdoor temp (5 C) | 31.7 C |
| Moderate | Medium heat loss, cold outdoor (0 C) | 28.6 C |
| Leaky | High heat loss, very cold outdoor (-5 C) | 25.0 C |
| Borderline | High heat loss, limited heating power | 16.4 C (cannot reach 21 C) |

## What Is Tested

### Steady-State Convergence

Validates that the controller reaches and maintains target temperatures over 24-48 hours of simulated time.

- **Reachable setpoint** -- well-insulated room settles within 0.5 C of 21 C
- **Moderate demand** -- higher heat-loss room converges with duty cycle in the 40-95% range
- **Unreachable setpoint** -- borderline room saturates at 100% duty; integral clamps at maximum; room temperature reaches the physical limit
- **Cold start** -- starting from 10 C, the room reaches setpoint without excessive overshoot
- **Parameter sweep** -- convergence verified across two room types and three Ki gain values

### Borderline Duty Cycles

The controller quantizes valve run times: if the computed duty is below a minimum threshold (~7.5%), the valve may skip a period entirely. These tests verify stable behavior at the boundary.

- **Just above threshold** (~9.4% duty) -- valve fires each period, integral stays stable
- **Just below threshold** (~6% duty) -- valve mostly off, integral remains bounded, room stays warm from mild outdoor conditions
- **At threshold** (~7.5% duty) -- no integral drift or oscillation

### Anti-Windup

The PID integral term is clamped to [0, 100] to prevent unbounded accumulation. These tests verify the clamp works correctly and releases when conditions change.

- **Clamp at maximum** -- unreachable setpoint drives integral to exactly 100
- **Clamp at zero** -- room above setpoint keeps integral at 0 (no negative accumulation)
- **Below-threshold stability** -- very low duty demand does not cause integral drift
- **Recovery from clamp** -- after outdoor temperature warms and setpoint is lowered, integral decreases from the maximum

### Disturbance Recovery

Mid-simulation perturbations test the controller's ability to recover from real-world events.

- **Window open** -- 10-minute window opening with a 3 C temperature drop; room recovers without excessive overshoot
- **Setpoint change** -- raising setpoint from 21 C to 23 C mid-run; smooth approach to the new target
- **Outdoor temperature drop** -- outdoor drops from 5 C to -5 C; duty cycle increases and room temperature is maintained

### Multi-Zone Interactions

Multiple zones share the heating system and compete for quota within each observation period.

- **Fair quota sharing** -- three zones with different demands receive proportional heating time; the zone with higher heat loss gets more duty
- **Saturated zone isolation** -- one zone at an unreachable setpoint (100% duty) does not starve neighbouring zones
- **DHW interruption** -- a 20-minute domestic hot water priority event suspends zone heating; all zones recover afterwards

## Running the Tests

```bash
# Simulation tests only (~1 second)
uv run pytest tests/simulations/ -v

# Full test suite
uv run pytest
```

The simulation tests are pure computation with no I/O, network, or Home Assistant dependencies. They run in under one second.
