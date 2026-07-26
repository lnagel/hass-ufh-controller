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

## Controller Status

Derived from zone statuses:

| Condition | Controller Status |
|-----------|-------------------|
| All zones normal | `normal` |
| Some zones failing, at least one normal | `degraded` |
| All zones in fail-safe | `fail_safe` |

The `binary_sensor.{controller_id}_status` entity shows `on` (problem) when degraded or fail-safe.

## Summer Mode Safety

When a zone is in fail-safe its valve is forced closed, so the controller can no
longer deliver heat to it. In `heat` mode the controller therefore sets summer
mode to "auto", handing the heating circuit back to the boiler so valve
controllers acting as offline thermostats can still receive heated water.

This applies in `heat` mode only, whether one zone or all zones have failed. Every
other mode is an explicit instruction that a zone failure must not override:

| Mode | Summer mode while any zone is in fail-safe |
|------|--------------------------------------------|
| `heat` | `auto` — delegated to the boiler |
| `flush` | `summer` — circulation only, no firing |
| `cycle` | `summer` — maintenance rotation, no firing |
| `all_on` | `winter` |
| `all_off` | `summer` |
| `off` | not written |

Delegating in a mode that must not fire the boiler would let the boiler heat on
its own curve while the controller reports no heat request. Because the failed
zones' valves are closed, that heat would be driven into whichever zones remain
open, with no PID, quota or window blocking applied.

Frost protection does not depend on this: the boiler applies its own internal
frost protection regardless of summer mode.
