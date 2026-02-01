# Heat Accounting

Underfloor heating systems need accurate heat accounting to fairly allocate heating time quotas across zones. When
multiple zones share a single heat source, simply tracking valve-open duration doesn't reflect actual heat delivered—a
zone with its valve open while the boiler is cold receives far less heat than one open during peak supply temperature.

## Supply Temperature Weighting

The chosen approach requires only a single additional sensor (manifold supply temperature) and naturally handles boiler
cycling: when the boiler fires, supply temperature rises and quota accumulates faster; during coast-down, supply
temperature decays and quota accumulation slows proportionally. This provides a practical approximation of heat delivery
without the complexity, cost, or failure modes of the alternatives.

When no supply temperature sensor is configured, the system falls back to simple time-based quota tracking.

See [Configuration](configuration.md#heat-accounting) for detailed parameter documentation.

### Supply Coefficient

When a supply temperature sensor is configured, the controller calculates a supply coefficient for each zone:

```
supply_coefficient = (supply_temp - room_temp) / (supply_target_temp - room_temp) × 100
```

- **100%**: Supply at target temperature (normal operation)
- **50%**: Supply halfway between room and target (boiler warming up)
- **150%**: Supply above target (boiler overshooting)
- **0%**: Supply at room temperature (no heat delivery)

The coefficient is capped at 200% to prevent runaway accumulation.

### Used Duration Accumulation

Each update cycle, `used_duration` accumulates when the zone is receiving heat:

1. **Flow requirement**: Only accumulates when `flow=True` (valve open ≥85% of detection window)
2. **Weighted**: `used_duration += dt × (supply_coefficient / 100)`
3. **Fallback**: Without a supply sensor, uses simple time: `used_duration += dt`

At each observation period boundary (default: every 2 hours) all zones' `used_duration` resets to 0

## Alternatives Considered

**1. Full ΔT-based thermal energy calculation (Q = ṁ × c × ΔT)**

Requires both supply and return temperature sensors at each zone or manifold, plus a flow meter or flow estimation.
Additionally, when the boiler cycles off, the supply-return ΔT collapses while stored thermal energy in the water mass
continues heating zones ("coast-down"), requiring complex water mass energy balance calculations to avoid
under-counting.

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
