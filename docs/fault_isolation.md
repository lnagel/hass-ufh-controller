# Fault Isolation

The controller implements zone-level fault isolation to ensure that failures in one zone do not affect other zones.

## Zone Status

Each zone tracks its own operational status:

| Status | Description |
|--------|-------------|
| `initializing` | Zone starting up; awaiting first successful temperature reading |
| `normal` | Zone operating normally with valid temperature readings |
| `degraded` | Temperature sensor or valve entity unavailable; using last-known duty cycle |
| `fail_safe` | No successful update within timeout; valve forced closed |

**Initializing:** No valve actions are taken until all zones have valid readings and exit initialization. Entities remain available using restored state from storage.

**Degraded:** PID continues with cached demand, zone still responds to setpoint changes. Triggered by temperature sensor unavailability or valve entity unavailability.

**Fail-safe:** Valve forced closed, zone excluded from heating. During initialization (no prior successful update), fail-safe activates after 2 minutes of continuous failures to surface misconfigurations quickly. After normal operation, the timeout is 1 hour.

## Zone Isolation Guarantee

**Critical:** Working zones are NEVER affected by failing zones.

| Scenario | Result |
|----------|--------|
| 1 of 7 zones fails | 6 zones continue operating |
| 6 of 7 zones fail | 1 zone continues operating |
| All zones fail | Controller enters fail-safe |

## Outdoor Temperature Initialization

When an outdoor temperature sensor is configured, the controller waits up to 2 minutes for it during initialization. If still unavailable after the timeout, the controller proceeds with the fallback supply target and reports `degraded`. If the sensor becomes unavailable during normal operation, the controller also reports `degraded`.

## Controller Status

Derived from zone statuses and outdoor temperature availability:

| Condition | Controller Status |
|-----------|-------------------|
| All zones normal, outdoor temp OK | `normal` |
| Some zones failing, at least one normal | `degraded` |
| Outdoor temp configured but unavailable (post-init) | `degraded` |
| All zones in fail-safe | `fail_safe` |

The `binary_sensor.{controller_id}_status` entity shows `on` (problem) when degraded or fail-safe.

## Summer Mode Safety

When ANY zone is in fail-safe:
- Summer mode forced to "auto"
- Allows physical fallback valves to receive heated water
- Ensures heating available via physical fallback mechanisms
