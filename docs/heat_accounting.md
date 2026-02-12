# Heat Accounting

Multi-zone underfloor heating systems need fair quota allocation. When multiple zones share a single heat source, simply
tracking valve-open duration penalizes zones that happen to be open when the boiler is cold—they consume their time
quota while receiving less heating benefit than zones open at peak supply temperature.

## Supply Temperature Normalization

The chosen approach mirrors the principle behind EN 834 electronic heat cost allocators — integrating temperature
difference over time rather than time alone. It requires only a supply temperature sensor and naturally handles boiler
cycling: when the boiler fires, supply temperature rises and quota consumption increases; during coast-down, supply
temperature decays and quota consumption slows proportionally. This normalizes quota usage to actual supply conditions
without the complexity, cost, or failure modes of the alternatives.

The normalization ignores per-circuit flow rate differences and floor covering resistance, but for relative allocation
among zones on a single manifold it is a meaningful improvement over pure time tracking.

When no supply temperature sensor is configured, the system falls back to simple time-based quota tracking.

See [Configuration](configuration.md#heat-accounting) for detailed parameter documentation.

### Supply Coefficient

When a supply temperature sensor is configured, the controller calculates a supply coefficient for each zone:

```
supply_coefficient = (supply_temp - room_temp) / (supply_target_temp - setpoint) × 100
```

The coefficient scales quota consumption relative to design conditions. At 100%, quota accumulates at the normal rate.
When supply temperature is low (boiler warming up), the coefficient drops below 100% and quota consumption slows—the
zone can stay open longer to compensate. When the room is colder than setpoint, the larger temperature differential
means the zone receives more benefit, reflected in a coefficient above 100%.

| Scenario | Supply | Room | Setpoint | Coefficient |
|----------|--------|------|----------|-------------|
| Design conditions | 40°C | 20°C | 20°C | 100% |
| Cold room heating up | 40°C | 15°C | 20°C | 125% |
| Room overshooting | 40°C | 22°C | 20°C | 90% |
| Boiler warming up | 30°C | 20°C | 20°C | 50% |
| Supply = room temp | 20°C | 20°C | 20°C | 0% |

The coefficient is capped at 200% to prevent runaway accumulation.

### Used Duration Accumulation

Each update cycle, `used_duration` accumulates when the zone is receiving heat:

1. **Flow requirement**: Only accumulates when `flow=True` (estimated valve position ≥ 0.85)
2. **Weighted**: `used_duration += dt × (supply_coefficient / 100)`
3. **Fallback**: Without a supply sensor, uses simple time: `used_duration += dt`

At each observation period boundary (default: every 2 hours) all zones' `used_duration` resets to 0

## Alternatives Considered

**1. Full ΔT-based thermal energy calculation (Q = ṁ × c × ΔT)**

EN 1434 mandates flow sensors, paired temperature sensors, and calculators for thermal energy measurement. Instrumenting
a 6-zone manifold would require 6 flow meters, 12 temperature sensors, and 6 calculators. Additionally, when the boiler
cycles off, the supply-return ΔT collapses while the floor's thermal mass continues heating the room ("coast-down"),
requiring complex energy balance calculations to avoid under-counting.

**2. Boiler energy meter apportionment**

Relies on the boiler reporting a thermal energy counter (e.g., via EMS-ESP), then apportioning energy to zones by their
nominal flow ratings. While accurate, this requires specific boiler hardware support and calibrated per-zone flow data
that many installations lack.

**3. Zone-level supply/return sensor pairs**

The most accurate approach, but requires 2× sensors per zone (potentially 16+ sensors for an 8-zone system), significant
wiring complexity, and per-zone flow knowledge for proper energy calculation.

**4. Flow meter at manifold with zone flow estimation**

Requires additional hardware and still needs supply/return temperatures for energy calculation, falling back to the
coast-down complexity of option 1.
