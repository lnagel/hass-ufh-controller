# Fault Isolation

The controller implements zone-level fault isolation to ensure that failures in one zone do not affect other zones.

## Zone Status

Each zone tracks its own operational status:

| Status | Description |
|--------|-------------|
| `initializing` | Zone starting up; awaiting first successful temperature reading |
| `normal` | Zone operating normally with valid temperature readings |
| `degraded` | Temperature sensor or valve entity unavailable; using last-known duty cycle |
| `fail_safe` | No successful update for >1 hour; valve forced closed |

**Initializing:** No valve actions are taken until all zones have valid readings and exit initialization. Entities remain available using restored state from storage.

**Degraded:** PID continues with cached demand, zone still responds to setpoint changes. Triggered by temperature sensor unavailability, valve entity unavailability, or Recorder query failure.

**Fail-safe:** Valve forced closed, zone excluded from heating. Recovery requires successful temperature reading.

## Zone Isolation Guarantee

**Critical:** Working zones are NEVER affected by failing zones.

| Scenario | Result |
|----------|--------|
| 1 of 7 zones fails | 6 zones continue operating |
| 6 of 7 zones fail | 1 zone continues operating |
| All zones fail | Controller enters fail-safe |

## Controller Status

Derived from zone statuses:

| Condition | Controller Status |
|-----------|-------------------|
| All zones normal | `normal` |
| Some zones failing, at least one normal | `degraded` |
| All zones in fail-safe | `fail_safe` |

The `binary_sensor.{controller_id}_status` entity shows `on` (problem) when degraded or fail-safe.

## Summer Mode Safety

When ANY zone is in fail-safe:
- Summer mode forced to "auto"
- Allows physical fallback valves to receive heated water
- Ensures heating available via physical fallback mechanisms
