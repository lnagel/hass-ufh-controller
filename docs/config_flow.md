# Config Flow Design


The integration uses a **subentry-based architecture** for zone management, providing native Home Assistant UI patterns:
- Zones appear as separate devices linked to their subentries
- Zone devices can be deleted directly from the HA device page
- Zone settings are accessed via the device's "Configure" button

### Initial Setup (ConfigFlow)

**Step 1: Controller Setup**

Creates the main ConfigEntry. Zones are added separately after setup.

To control the boiler, configure either a Heat Request Switch or Summer Mode Select entity. If neither is configured, the boiler must remain operational continuously.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Controller display name |
| controller_id | string | Auto | Unique ID (auto-generated from name) |
| heat_request_entity | entity (switch) | No | Switch to signal heat demand to boiler |
| dhw_active_entity | entity (binary_sensor) | No | Sensor indicating DHW tank is heating |
| circulation_entity | entity (binary_sensor) | No | Sensor indicating circulation pump is running |
| summer_mode_entity | entity (select) | No | Select to enable/disable boiler UFH circuit |

On entry setup, a **controller subentry** is automatically created to:
- Store timing parameters
- Link controller-level entities (mode select, heat request switch, etc.) to a device
- Enable the "Configure" button on the controller device

### Zone Subentry Flow

Zones are managed as **config subentries**. Users interact with zones through:

**Adding a Zone:**
- Navigate to: Settings → Devices & Services → Underfloor Heating Controller → "+ Add Heating Zone"
- Or: Device page → Controller device → "Add Heating Zone" button

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Zone display name |
| temp_sensor | entity (sensor) | Yes | Temperature sensor for this zone |
| valve_switch | entity (switch) | Yes | Valve control switch |
| circuit_type | select | No | "regular" (default) or "flush" |
| window_sensors | multi-entity | No | Window/door sensors that block this zone |
| setpoint_min | float | No | Minimum allowed setpoint (default: 16°C) |
| setpoint_max | float | No | Maximum allowed setpoint (default: 28°C) |
| setpoint_default | float | No | Initial setpoint (default: 21°C) |
| temp_ema_time_constant | number (s) | No | Temperature EMA filter time constant (default: 600s / 10 min) |
| kp | float | No | PID proportional gain (default: 50.0) |
| ki | float | No | PID integral gain (default: 0.001) |
| kd | float | No | PID derivative gain (default: 0.0) |

**Reconfiguring a Zone:**
- Navigate to: Settings → Devices & Services → Devices → [Zone Device] → "Configure" (cogwheel)
- All fields from zone creation are editable except the zone ID

**Deleting a Zone:**
- Navigate to: Settings → Devices & Services → Devices → [Zone Device] → Delete
- The subentry and all associated entities are removed

### Options Flow (Timing Settings)

Accessed via: Settings → Devices & Services → Underfloor Heating Controller → Configure

The options flow provides access to **timing parameters** that apply to the entire controller:

| Field | Type | Description |
|-------|------|-------------|
| observation_period | number (s) | Time window for quota-based scheduling (default: 7200s / 2h) |
| min_run_time | number (s) | Minimum valve on duration (default: 540s / 9min) |
| valve_open_time | number (s) | Time to detect valve fully open (default: 210s / 3.5min) |
| closing_warning_duration | number (s) | Warning before valve closes (default: 240s / 4min) |
| window_block_time | number (s) | Window open time to trigger blocking (default: 600s / 10min) |
| controller_loop_interval | number (s) | PID update interval (default: 60s / 1min) |
| flush_duration | number (s) | Flush duration after DHW ends (default: 480s / 8min) |

These settings are stored in the **controller subentry** data.

### Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        ConfigEntry                              │
│  data: {name, controller_id, heat_request_entity, ...}         │
├─────────────────────────────────────────────────────────────────┤
│                        Subentries                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Controller Subentry (auto-created)                       │  │
│  │  - type: "controller"                                     │  │
│  │  - data: {timing: {...}}                                  │  │
│  │  - Entities: mode select, flush enabled switch,           │  │
│  │              requesting zones sensor                      │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Zone Subentry (user-created via "+ Add Heating Zone")   │  │
│  │  - type: "zone"                                           │  │
│  │  - data: {id, name, temp_sensor, valve_switch, pid, ...} │  │
│  │  - Entities: climate, duty_cycle sensor, pid sensors,     │  │
│  │              blocked binary_sensor, heat_request sensor  │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ... (more zone subentries)                                    │
└─────────────────────────────────────────────────────────────────┘
```

---
