# Entity Model


### Controller-Level Entities

All controller entities belong to a device named after the controller (user-defined).

| Platform | Entity ID Pattern                          | Name                       | Description |
|----------|--------------------------------------------|----------------------------|-------------|
| select | `select.{controller_id}_mode`              | "{name} Mode"              | Control mode selector |
| switch | `switch.{controller_id}_flush_enabled`     | "{name} Flush Enabled"     | DHW latent heat capture toggle (only when `dhw_active_entity` configured) |
| sensor | `sensor.{controller_id}_zones_flowing`  | "{name} Zones Flowing"  | Count of zones with active water flow |
| sensor | `sensor.{controller_id}_zones_heating`  | "{name} Zones Heating"  | Count of zones currently receiving heat |
| sensor | `sensor.{controller_id}_zones_window`  | "{name} Zones Window"  | Count of zones with recent window activity |
| sensor | `sensor.{controller_id}_supply_target_temp`     | "{name} Supply Target Temperature"     | Calculated supply target from heating curve (only when `outdoor_temp_entity` configured) |
| binary_sensor | `binary_sensor.{controller_id}_status` | "{name} Status" | Controller operational status (problem when degraded/fail-safe); `fail_safe_reason` attribute names the cause |
| binary_sensor | `binary_sensor.{controller_id}_pump_request` | "{name} Pump Request" | Pump is requested for water circulation through zones |
| binary_sensor | `binary_sensor.{controller_id}_heat_request` | "{name} Heat Request" | Controller is requesting heat from the boiler |
| binary_sensor | `binary_sensor.{controller_id}_flush_request` | "{name} Flush Request" | Flush is actively running (only when `dhw_active_entity` configured) |
| binary_sensor | `binary_sensor.{controller_id}_dhw_block` | "{name} DHW Block" | Absolute DHW priority is holding circuits closed (only when `dhw_active_entity` configured) |

**Note:** The flush enabled switch, flush request sensor and DHW block sensor are only created when `dhw_active_entity` is configured, as all three require DHW state input to function.

**DHW Block Behavior:**
The DHW block sensor reports whether the [absolute DHW priority](configuration.md#dhw_priority) block *condition* is in force — not whether valves are currently closed:
- **ON:** While DHW is charging, and throughout the `dhw_recovery_time` hold-off after it ends
- **OFF:** Whenever `dhw_priority` is `parallel` or `partial`, since neither closes running circuits
- **Manual override modes ignore it:** `heat`, `flush` and `cycle` act on the block; `all_on` and `off` do not, so the sensor can read ON while those modes hold valves open. Read it alongside the mode select rather than as a guarantee about valve positions
- **Attributes:** `dhw_priority` (the configured level), `dhw_active` (resolved DHW state), `dhw_sensor_available` (false while the DHW sensor is unavailable and the block is being held) and `dhw_block_until` (when the hold-off expires)
- **Survives restarts:** the recovery deadline is persisted, so a restart or an options change mid-recovery does not release circuits early. Only deadlines are restored; everything else is recomputed from live inputs
- **DHW sensor unreadable:** under `absolute` this is a fault — circuits are blocked and the controller goes `degraded`, escalating to `fail_safe` after an hour. Detected on the next control cycle rather than instantly, which debounces brief dropouts. See [dhw_priority](configuration.md#dhw_priority)
- **Only armed under `absolute`:** `dhw_block_until` stays empty for `parallel` and `partial`, since no block can engage there

**Flush Enabled Behavior:**
- **Enabled:** Flush-type circuits can turn on for a configurable period after DHW ends (`flush_duration`) to capture latent heat (only when no regular circuits are currently running with valve ON).
- **Disabled:** Flush-type circuits behave like regular circuits — no special DHW priority.
- **DHW priority for regular zones is independent of this setting.** Under the default `partial` priority, regular zones that are OFF cannot turn ON during DHW heating regardless of the flush enabled state. This switch only controls whether flush circuits get special treatment.
- **Under `absolute` priority, latent heat capture is deferred, not cancelled.** The flush window opens only after `dhw_recovery_time` has elapsed, at its full `flush_duration`. Consider leaving this switch off on unmixed systems — see [dhw_priority](configuration.md#dhw_priority).

**Flush Request Behavior:**
The flush request sensor indicates when flush circuits are actively capturing heat:
- **ON:** During the post-DHW flush period
- **OFF:** When DHW is active, when a DHW block is in force, or when not within the post-DHW flush period
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
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_flow` | "{zone_name} Flow" | Water actively flowing through zone |
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_heat` | "{zone_name} Heat" | Zone is actively receiving useful heat |
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_window` | "{zone_name} Window" | Window was recently open (PID control paused) |
| sensor | `sensor.{controller_id}_{zone_id}_supply_coefficient` | "{zone_name} Supply Coefficient" | Quota consumption rate relative to design conditions |

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
| `HVACAction.IDLE` | Zone is enabled but not actively receiving heat |
| `HVACAction.HEATING` | Zone is actively receiving heat (flow established and supply conditions met) |

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

**Note:** Controller-level entities (mode select, zone counting sensors, status binary sensor) remain available regardless of individual zone status.

---
