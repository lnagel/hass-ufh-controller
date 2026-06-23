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

**Back-calculation anti-windup:** At each observation period boundary, the controller compares actual delivery (`used_duration`) against the commanded output recorded at the last convergence point. Convergence points are bumped forward at valve open, valve close, and period start — tracking *when* the last decision was made and *what was requested* at that point. If the valve delivered less than commanded — typically because the duty cycle was too small for the minimum run time — a correction is applied: `integral += Kt × (u_actual − u_commanded) × period`, where `Kt = Ki/Kp`. This gradually adjusts the integral to reflect what was actually delivered, preventing excessive overshoot when demand later increases above the delivery threshold.

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

1. **Flush circuit priority:** If flush is enabled and DHW has recently ended with no regular circuits currently running, flush circuits turn on to capture latent heat from the boiler.

2. **End-of-period freeze:** When less than `min_run_time` remains in the observation period, valve positions are frozen to prevent unnecessary cycling at period boundaries.

3. **Quota-based scheduling:** For zones that haven't met their quota:
   - If valve is already on: stay on (commands are re-sent to prevent relay timeout)
   - If estimated wall clock runtime is less than `min_run_time`: stay off (not worth a short run).
     When a supply coefficient is available, remaining quota is converted to estimated wall clock time
     (capped at remaining quota so coefficients above 100% never shorten the estimate):
     `estimated_runtime = max(remaining_quota, remaining_quota / (supply_coefficient / 100))`.
     Without a supply sensor, remaining quota is compared directly.
   - If DHW is active and this is a regular circuit currently off: stay off (DHW priority)
   - Otherwise: turn on

4. **Quota met:** For zones that have met their quota:
   - If valve is on: turn off
   - If valve is off: stay off

**Note:** Window blocking affects PID integration (pausing accumulation), not valve control directly. Valves follow quota-based scheduling regardless of window state.

### Heat Request Logic

The controller computes a single heat request signal from all zones with active flow:
- Only zones with `flow=True` (valve confirmed fully open) are considered
- A zone contributes to the heat request when its `remaining_duration` exceeds the `closing_warning_duration` (zone won't close imminently)
- If any qualifying zone needs heat, the boiler heat request is enabled

### Boiler Summer Mode Management

When a summer mode entity is configured and the controller is in automatic mode:
- If heat is requested and summer mode is not "winter": switch to "winter" (enables heating circuit)
- If no heat is requested and summer mode is not "summer": switch to "summer" (disables heating circuit, saves energy)

---
