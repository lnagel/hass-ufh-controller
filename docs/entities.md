# Entity Model


### Controller-Level Entities

All controller entities belong to a device named after the controller (user-defined).

| Platform | Entity ID Pattern                          | Name                       | Description |
|----------|--------------------------------------------|----------------------------|-------------|
| select | `select.{controller_id}_mode`              | "{name} Mode"              | Control mode selector |
| switch | `switch.{controller_id}_flush_enabled`     | "{name} Flush Enabled"     | DHW latent heat capture toggle (only when `dhw_active_entity` configured) |
| sensor | `sensor.{controller_id}_requesting_zones`  | "{name} Requesting Zones"  | Count of zones currently requesting heat |
| binary_sensor | `binary_sensor.{controller_id}_status` | "{name} Status" | Controller operational status (problem when degraded/fail-safe) |
| binary_sensor | `binary_sensor.{controller_id}_flush_request` | "{name} Flush Request" | Flush is actively running (only when `dhw_active_entity` configured) |

**Note:** The flush enabled switch and flush request sensor are only created when `dhw_active_entity` is configured, as the DHW latent heat capture feature requires DHW state input to function.

**Flush Enabled Behavior:**
- **Enabled:** Flush-type circuits can turn on for a configurable period after DHW ends (`flush_duration`) to capture latent heat (only when no regular circuits are currently running with valve ON).
- **Disabled:** Flush-type circuits behave like regular circuits — no special DHW priority.
- **DHW priority for regular zones is independent of this setting.** Regular zones that are OFF cannot turn ON during DHW heating regardless of the flush enabled state. This switch only controls whether flush circuits get special treatment.

**Flush Request Behavior:**
The flush request sensor indicates when flush circuits are actively capturing heat:
- **ON:** During the post-DHW flush period
- **OFF:** When DHW is active or not within the post-DHW flush period
- **Requires flush_enabled:** The sensor only reports ON if `flush_enabled` switch is also on

**Select Options for Mode:**

| Value | Label | Description |
|-------|-------|-------------|
| `heat` | Heat | Normal PID-based operation |
| `flush` | Flush | All valves open, boiler circulation only (no firing) |
| `cycle` | Cycle | Rotate through zones on 8-hour schedule |
| `all_on` | All On | All valves open, heating enabled |
| `all_off` | All Off | All valves closed, heating disabled |
| `off` | Off | Controller inactive, no actions taken |

### Zone-Level Entities

Each zone gets its own device named after the zone (user-defined). The valve switch entity is user-provided during zone configuration. If an area is configured for the zone, all zone entities are automatically assigned to that Home Assistant Area.

| Platform | Entity ID Pattern | Name | Description |
|----------|-------------------|------|-------------|
| climate | `climate.{controller_id}_{zone_id}` | "{zone_name}" | Primary control entity |
| sensor | `sensor.{controller_id}_{zone_id}_duty_cycle` | "{zone_name} Duty Cycle" | PID output (0-100%) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_error` | "{zone_name} PID Error" | Current temperature error (setpoint - current) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_proportional` | "{zone_name} PID Proportional" | Proportional term (Kp * error) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_integral` | "{zone_name} PID Integral" | Integral term (Ki * accumulated error) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_derivative` | "{zone_name} PID Derivative" | Derivative term (Kd * rate of change) |
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_blocked` | "{zone_name} Blocked" | Zone PID control paused (window was recently open) |
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_heat_request` | "{zone_name} Heat Request" | Zone is contributing to heat request |

### Climate Entity Details

**Supported Features:**
- `ClimateEntityFeature.TARGET_TEMPERATURE`
- `ClimateEntityFeature.PRESET_MODE` (if presets configured)
- `ClimateEntityFeature.TURN_ON`
- `ClimateEntityFeature.TURN_OFF`

**HVAC Modes:**

| Mode | Behavior |
|------|----------|
| `HVACMode.HEAT` | Zone enabled, participates in automatic control |
| `HVACMode.OFF` | Zone disabled, valve forced closed |

**HVAC Actions:**

The `hvac_action` attribute communicates the current operational state of each zone:

| Action | Condition |
|--------|-----------|
| `HVACAction.OFF` | Heating is disabled (zone HVAC mode is OFF) |
| `HVACAction.IDLE` | Zone is not requesting heat |
| `HVACAction.HEATING` | Zone is requesting heat |

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `current_temperature` | float | Current zone temperature |
| `target_temperature` | float | Current setpoint |
| `min_temp` | float | Minimum allowed setpoint |
| `max_temp` | float | Maximum allowed setpoint |
| `target_temp_step` | float | Setpoint increment |
| `preset_mode` | string | Active preset (if any) |
| `preset_modes` | list | Available presets |

### Entity Availability Rules

Entity availability is determined by a combination of coordinator status and zone status.

| Entity Type | Available When |
|-------------|----------------|
| Climate (zone) | Coordinator updated |
| Sensor (zone) | Zone not FAIL_SAFE AND native value not None |
| Binary Sensor (zone) | Zone not FAIL_SAFE |
| Controller entities | Coordinator updated |

**Design Rationale:**
- **Climate unavailable when temp sensor fails:** Prevents "unknown" states from being recorded to history
- **Zone sensors/binary sensors unavailable during FAIL_SAFE:** Zone not participating in control, values would be misleading

**Note:** Controller-level entities (mode select, requesting zones sensor, status binary sensor) remain available regardless of individual zone status.

---
