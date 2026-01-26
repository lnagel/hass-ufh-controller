# Control Algorithm


### Execution Cycle

The coordinator runs every **60 seconds** and performs:

1. **PID Update** (per zone)
2. **Historical State Query** (per zone)
3. **Zone Decision** (per zone)
4. **Heat Request Aggregation**
5. **Boiler Mode Management**

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

| Window | Duration | Calculation |
|--------|----------|-------------|
| **Observation Period** | 2 hours (default) | Aligned to even hours (00:00, 02:00, 04:00...) |
| **Valve Open Detection** | 3.5 minutes | Fixed window for detecting valve fully open |

**Observation Period Alignment:** Periods always start at even hours (midnight, 2am, 4am, etc.) regardless of when the controller started. This ensures consistent quota scheduling and predictable behavior. Commands are re-sent at least once per period for external dead-man-switch compatibility.

### Zone Decision Tree

The zone evaluation follows a priority-based decision tree:

1. **Flush circuit priority:** If flush is enabled and DHW has recently ended with no regular circuits currently running, flush circuits turn on to capture latent heat from the boiler.

2. **End-of-period freeze:** When less than `min_run_time` remains in the observation period, valve positions are frozen to prevent unnecessary cycling at period boundaries.

3. **Quota-based scheduling:** For zones that haven't met their quota:
   - If valve is already on: stay on (commands are re-sent to prevent relay timeout)
   - If remaining quota is less than `min_run_time`: stay off (not worth a short run)
   - If DHW is active and this is a regular circuit currently off: stay off (DHW priority)
   - Otherwise: turn on

4. **Quota met:** For zones that have met their quota:
   - If valve is on: turn off
   - If valve is off: stay off

**Note:** Window blocking affects PID integration (pausing accumulation), not valve control directly. Valves follow quota-based scheduling regardless of window state.

### Heat Request Logic

A zone contributes to the heat request when all conditions are met:
- Valve is currently on
- Valve has been on for at least 85% of the valve open detection window (confirming the valve is fully open)
- Remaining quota is at least the closing warning duration (zone won't close imminently)

The controller aggregates heat requests from all zones: if any zone requests heat, the boiler heat request is enabled.

### Boiler Summer Mode Management

When a summer mode entity is configured and the controller is in automatic mode:
- If heat is requested and summer mode is not "winter": switch to "winter" (enables heating circuit)
- If no heat is requested and summer mode is not "summer": switch to "summer" (disables heating circuit, saves energy)

---
