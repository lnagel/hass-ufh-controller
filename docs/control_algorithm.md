# Control Algorithm


### Execution Cycle

The coordinator runs every **60 seconds** and performs:

1. **PID Update** (per zone)
2. **Historical State Query** (per zone)
3. **Zone Decision** (per zone)
4. **Pump & Heat Request Aggregation**
5. **Safety Lockout**
6. **Boiler Mode Management**

### PID Controller

The PID controller calculates a duty cycle (0-100%) from the temperature error (setpoint minus current temperature).

**Calculation:**
- **Proportional term:** Kp × error (immediate response to temperature deviation)
- **Integral term:** Ki × accumulated error over time (eliminates steady-state error)
- **Derivative term:** Kd × rate of error change (damping, typically disabled for slow hydronic systems)

**Anti-windup protection:** The integral term is clamped between configurable limits (default 0-100%) to prevent unbounded accumulation when the system cannot reach setpoint.

**Output clamping:** The final duty cycle is clamped to 0-100%.

### PID Integration Pausing

To prevent integral windup during periods when heating is blocked or irrelevant, the PID controller's `update()` method is skipped (integration paused) when any of the following conditions are true:

| Condition | Reason |
|-----------|--------|
| Temperature unavailable | Cannot calculate meaningful error without current temperature |
| Controller mode ≠ `heat` | PID control only applies in heat mode |
| Zone disabled | Disabled zones don't participate in heating |
| Window open (above threshold) | Heating blocked, would cause integral windup |

When paused:
- The integral term is frozen at its current value
- The duty cycle is maintained at its last calculated value
- The error term is still updated (for UI display purposes)

This prevents the common problem of integral windup where the integral term accumulates while the room temperature is unstable after a window opening, which would cause overshoot when normal control resumes.

### Time Windows

| Window | Duration | Calculation                                  |
|--------|----------|----------------------------------------------|
| **Observation Period** | 2 hours (default) | Aligned to midnight (00:00, 02:00, 04:00...) |
| **Valve Position Estimation** | 7 minutes (default) | `valve_open_time + valve_close_time` (physical position estimation) |

### Heat Accounting

Heat accounting tracks how much of its quota each zone has consumed during the observation period, with optional supply-temperature normalization to adjust for actual heating conditions.

**Key concepts:**
- `used_duration` accumulates only when `flow=True` (valve confirmed open)
- When a supply temperature sensor is configured, accumulation is weighted by the supply coefficient
- At period boundaries, all zones reset to fresh quota

See [Heat Accounting](heat_accounting.md) for detailed documentation.

### Zone Decision Tree

The zone evaluation follows a priority-based decision tree:

1. **Absolute DHW priority:** If `dhw_priority` is `absolute` and DHW is charging (or the `dhw_recovery_time` hold-off has not expired), every circuit is driven closed. This overrides all the steps below, including the already-on and end-of-period-freeze paths, because the hazard it guards against is hydraulic rather than thermal — see [dhw_priority](configuration.md#dhw_priority).

2. **Flush circuit priority:** If flush is enabled and DHW has recently ended with no regular circuits currently running, flush circuits turn on to capture latent heat from the boiler.

3. **End-of-period freeze:** When less than `min_run_time` remains in the observation period, valve positions are frozen to prevent unnecessary cycling at period boundaries.

4. **Quota-based scheduling:** For zones that haven't met their quota:
   - If valve is already on: stay on (commands are re-sent to prevent relay timeout)
   - If estimated wall clock runtime is less than `min_run_time`: stay off (not worth a short run).
     When a supply coefficient is available, remaining quota is converted to estimated wall clock time
     (capped at remaining quota so coefficients above 100% never shorten the estimate):
     `estimated_runtime = max(remaining_quota, remaining_quota / (supply_coefficient / 100))`.
     Without a supply sensor, remaining quota is compared directly.
   - If `dhw_priority` is `partial` (the default), DHW is active and this is a regular circuit currently off: stay off. Circuits already running are left alone; `parallel` skips this check entirely.
   - Otherwise: turn on

5. **Quota met:** For zones that have met their quota:
   - If valve is on: turn off
   - If valve is off: stay off

**Note:** Window blocking affects PID integration (pausing accumulation), not valve control directly. Valves follow quota-based scheduling regardless of window state. Absolute DHW priority is the one exception that does close valves, since no amount of PID pausing keeps DHW-temperature water out of the floor.

**Note:** PID integration continues normally during a DHW block. The room temperature reading stays valid and the room really is losing heat, so the integral builds and the zone catches up once the block clears.

**Note:** Quota is preserved rather than compensated, but not instantly. `used_duration` accrues while `flow` is true, and `flow` is derived from the estimated valve position, which ramps down over `valve_close_time` after the block commands the valve shut. A zone therefore keeps consuming quota for roughly the first 15% of `valve_close_time` (about 30 s at the default 210 s) before flow drops below the 0.85 threshold. That is deliberate: during that window the circuit is receiving cylinder-temperature water, so it is being charged for heat it genuinely got. If DHW spans an observation-period boundary the unused remainder is dropped, which the PID integral self-corrects over the next period.

### Heat Request Logic

The controller computes a single heat request signal from all zones with active flow:
- Only zones with `flow=True` (valve confirmed fully open) are considered
- A zone contributes to the heat request when its `remaining_duration` exceeds the `closing_warning_duration` (zone won't close imminently)
- If any qualifying zone needs heat, the boiler heat request is enabled
- While a DHW block is in force the heat request is suppressed outright. Thermal actuators take minutes to close, so a circuit still reports flow immediately after DHW asserts; without this the controller would ask the boiler to fire for space heating mid-charge. Pump request stays flow-driven and decays naturally as the valves close.

### Boiler Summer Mode Management

When a summer mode entity is configured and the controller is in automatic mode:
- If heat is requested and summer mode is not "winter": switch to "winter" (enables heating circuit)
- If no heat is requested and summer mode is not "summer": switch to "summer" (disables heating circuit, saves energy)

---
