# Heating Controller - Home Assistant Custom Integration Specification

This document specifies a custom Home Assistant integration for multi-zone hydronic heating control with PID-based temperature regulation. The design is based on a proven OpenHAB implementation.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Data Model](#3-data-model)
4. [Config Flow Design](#4-config-flow-design)
5. [Entity Model](#5-entity-model)
6. [Control Algorithm](#6-control-algorithm)
7. [Operation Modes](#7-operation-modes)
8. [Historical State Queries](#8-historical-state-queries)
9. [Project Structure](#9-project-structure)
10. [Testing Strategy](#10-testing-strategy)
11. [CI/CD Pipeline](#11-cicd-pipeline)
12. [Risks & Mitigations](#12-risks--mitigations)
13. [Configuration Reference](#13-configuration-reference)

---

## 1. Overview

### 1.1 Purpose

A custom Home Assistant integration providing:

- **Multi-zone PID temperature control** for hydronic (water-based) heating systems
- **Coordinated valve management** with duty cycle-based scheduling
- **Safety interlocks** (window/door detection stops heating)
- **DHW latent heat capture** (flush circuits capture waste heat after hot water heating)
- **Multiple operation modes** (automatic, flush, cycle, manual overrides)

### 1.2 Design Principles

| Principle | Description |
|-----------|-------------|
| **Quality first** | Full test coverage, type checking, linting, CI pipeline |
| **Native HA integration** | Proper ConfigEntry, DataUpdateCoordinator, entity platforms |
| **User-friendly config** | UI-based Config Flow, no YAML required |
| **Multi-instance** | Support multiple independent controllers per HA instance |
| **Minimal dependencies** | Use HA's built-in Recorder for historical state queries |

### 1.3 Requirements

- **Home Assistant**: 2025.10+
- **Python**: 3.13+

---

## 2. Architecture

### 2.1 Two-Layer Control

```
┌─────────────────────────────────────────────────────────────────┐
│                      Coordination Layer                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  - Aggregates demand from all zones                       │  │
│  │  - Manages valve timing (min run time, open detection)    │  │
│  │  - Handles window blocking                                │  │
│  │  - DHW flush priority                                     │  │
│  │  - Generates single heat request to boiler                │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐              │
│         ▼                    ▼                    ▼              │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐      │
│  │  Zone PID   │      │  Zone PID   │      │  Zone PID   │      │
│  │  Controller │      │  Controller │      │  Controller │      │
│  │             │      │             │      │             │      │
│  │ Duty Cycle  │      │ Duty Cycle  │      │ Duty Cycle  │      │
│  │   0-100%    │      │   0-100%    │      │   0-100%    │      │
│  └─────────────┘      └─────────────┘      └─────────────┘      │
│      Zone 1               Zone 2               Zone N           │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Heat Source      │
                    │  (Boiler/Heat Pump) │
                    └─────────────────────┘
```

### 2.2 Terminology

| Term | Description |
|------|-------------|
| **Controller** | One ConfigEntry controlling one heat source. Appears as a device in HA. |
| **Heat Source** | Gas boiler, heat pump, or other heat generator receiving the heat request signal |
| **Zone** | One heating circuit with valve, temperature sensor, and independent PID control |
| **Regular Circuit** | Standard heating zone |
| **Flush Circuit** | Zone (typically bathroom) that can capture latent heat during DHW cycles |
| **Duty Cycle** | PID output (0-100%) representing heating demand |
| **Observation Period** | Time window (default 2 hours) for quota-based valve scheduling |

---

## 3. Data Model

### 3.1 ConfigEntry Structure

The integration uses Home Assistant's **Config Subentries** feature (HA 2025.7+) to manage zones and controller settings. This enables:
- Native device deletion through the HA UI
- Zone configuration via the device "Configure" button
- Proper device-to-subentry linking in the UI

```python
ConfigEntry.data = {
    "name": "Heating Controller",           # User-defined controller name
    "controller_id": "heating",             # Unique ID for entity naming
    "heat_request_entity": "switch.boiler_heat_request",          # Optional
    "dhw_active_entity": "binary_sensor.boiler_tapwater_active",  # Optional
    "circulation_entity": "binary_sensor.boiler_circulation",     # Optional
    "summer_mode_entity": "select.boiler_summer_mode",            # Optional
}

# Options kept minimal (timing stored in controller subentry)
ConfigEntry.options = {}

# Subentries store zones and controller settings
ConfigEntry.subentries = {
    # Controller subentry (auto-created, stores timing settings)
    "controller_subentry_id": ConfigSubentry(
        subentry_type="controller",
        unique_id="controller",
        title="Heating Controller",
        data={
            "timing": {
                "observation_period": 7200,    # seconds (2 hours)
                "min_run_time": 540,           # seconds (9 minutes)
                "valve_open_time": 210,        # seconds (3.5 minutes)
                "closing_warning_duration": 240, # seconds (4 minutes)
                "window_block_time": 600       # seconds - block if window open this long
            }
        }
    ),

    # Zone subentries (one per heating zone)
    "zone_subentry_id_1": ConfigSubentry(
        subentry_type="zone",
        unique_id="living_room",
        title="Living Room",
        data={
            "id": "living_room",
            "name": "Living Room",
            "circuit_type": "regular",  # or "flush"
            "temp_sensor": "sensor.living_room_temperature",
            "valve_switch": "switch.living_room_valve",
            "window_sensors": [
                "binary_sensor.living_room_window",
                "binary_sensor.terrace_door"
            ],
            "setpoint": {
                "min": 18.0,
                "max": 25.0,
                "step": 0.5,
                "default": 21.0
            },
            "pid": {
                "kp": 50.0,
                "ki": 0.001,
                "kd": 0.0,
                "integral_min": 0.0,
                "integral_max": 100.0
            },
            "presets": {
                "home": 21.0,
                "away": 16.0,
                "eco": 19.0,
                "comfort": 22.0,
                "boost": 25.0
            }
        }
    ),
    # ... more zone subentries
}
```

### 3.2 Runtime State (Coordinator)

```python
@dataclass
class ZoneState:
    # PID state
    current_temp: float | None
    setpoint: float
    error: float
    integral: float
    duty_cycle: float  # 0-100

    # Valve state
    valve_on: bool
    valve_on_since: datetime | None

    # Calculated values (from Recorder queries)
    period_state_avg: float    # Average since observation_start
    open_state_avg: float      # Average over valve_open_time
    window_recently_open: bool # Was any window open within blocking period

    # Derived
    used_duration: float       # Seconds valve was on this period
    requested_duration: float  # Seconds valve should be on this period

@dataclass
class ControllerState:
    mode: str  # auto, flush, cycle, all_on, all_off, disabled
    observation_start: datetime
    period_elapsed: float  # Seconds elapsed in current observation period
    heat_request: bool
    flush_enabled: bool
    dhw_active: bool  # DHW tank is currently heating
    flush_until: datetime | None  # Timestamp when post-DHW flush period ends
    zones: dict[str, ZoneState]
```

---

## 4. Config Flow Design

The integration uses a **subentry-based architecture** for zone management, providing native Home Assistant UI patterns:
- Zones appear as separate devices linked to their subentries
- Zone devices can be deleted directly from the HA device page
- Zone settings are accessed via the device's "Configure" button

### 4.1 Initial Setup (ConfigFlow)

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

### 4.2 Zone Subentry Flow

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
| kp | float | No | PID proportional gain (default: 50.0) |
| ki | float | No | PID integral gain (default: 0.05) |
| kd | float | No | PID derivative gain (default: 0.0) |

**Reconfiguring a Zone:**
- Navigate to: Settings → Devices & Services → Devices → [Zone Device] → "Configure" (cogwheel)
- All fields from zone creation are editable except the zone ID

**Deleting a Zone:**
- Navigate to: Settings → Devices & Services → Devices → [Zone Device] → Delete
- The subentry and all associated entities are removed

### 4.3 Options Flow (Timing Settings)

Accessed via: Settings → Devices & Services → Underfloor Heating Controller → Configure

The options flow provides access to **timing parameters** that apply to the entire controller:

| Field | Type | Description |
|-------|------|-------------|
| observation_period | number (s) | Time window for quota-based scheduling (default: 7200s / 2h) |
| min_run_time | number (s) | Minimum valve on duration (default: 540s / 9min) |
| valve_open_time | number (s) | Time to detect valve fully open (default: 210s / 3.5min) |
| closing_warning_duration | number (s) | Warning before valve closes (default: 240s / 4min) |
| window_block_time | number (s) | Window open time to trigger blocking (default: 600s / 10min) |

These settings are stored in the **controller subentry** data.

### 4.4 Architecture Summary

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

## 5. Entity Model

### 5.1 Controller-Level Entities

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
- **Enabled:** Flush-type circuits can turn on during DHW heating AND for a configurable period after DHW ends (`flush_duration`) to capture latent heat (only when no regular circuits are currently running with valve ON).
- **Disabled:** Flush-type circuits behave like regular circuits — no special DHW priority.
- **DHW priority for regular zones is independent of this setting.** Regular zones that are OFF cannot turn ON during DHW heating regardless of the flush enabled state. This switch only controls whether flush circuits get special treatment.

**Flush Request Behavior:**
The flush request sensor indicates when flush circuits are actively capturing heat:
- **ON:** During DHW heating (when `dhw_active_entity` is on) OR during the post-DHW flush period
- **OFF:** When neither DHW is active nor within the post-DHW flush period
- **Requires flush_enabled:** The sensor only reports ON if `flush_enabled` switch is also on

**Select Options for Mode:**

| Value | Label | Description |
|-------|-------|-------------|
| `auto` | Automatic | Normal PID-based operation |
| `flush` | Flush | All valves open, boiler circulation only (no firing) |
| `cycle` | Cycle | Rotate through zones on 8-hour schedule |
| `all_on` | All On | All valves open, heating enabled |
| `all_off` | All Off | All valves closed, heating disabled |
| `disabled` | Disabled | Controller inactive, no actions taken |

### 5.2 Zone-Level Entities

Each zone gets its own device named after the zone (user-defined). The valve switch entity is user-provided during zone configuration. If an area is configured for the zone, all zone entities are automatically assigned to that Home Assistant Area.

| Platform | Entity ID Pattern | Name | Description |
|----------|-------------------|------|-------------|
| climate | `climate.{controller_id}_{zone_id}` | "{zone_name}" | Primary control entity |
| sensor | `sensor.{controller_id}_{zone_id}_duty_cycle` | "{zone_name} Duty Cycle" | PID output (0-100%) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_error` | "{zone_name} PID Error" | Current temperature error (setpoint - current) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_proportional` | "{zone_name} PID Proportional" | Proportional term (Kp * error) |
| sensor | `sensor.{controller_id}_{zone_id}_pid_integral` | "{zone_name} PID Integral" | Integral term (Ki * accumulated error) |
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_blocked` | "{zone_name} Blocked" | Zone PID control paused (window was recently open) |
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_heat_request` | "{zone_name} Heat Request" | Zone is contributing to heat request |

### 5.3 Climate Entity Details

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
| `HVACAction.IDLE` | Heating enabled but valve is closed (not currently heating) |
| `HVACAction.HEATING` | Valve is open (actively heating) |

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

### 5.4 Entity Availability Rules

Entity availability is determined by a combination of coordinator status and zone status.

| Entity Type | Available When |
|-------------|----------------|
| Climate (zone) | Coordinator updated AND current temperature known |
| Sensor (zone) | Zone NORMAL or DEGRADED AND native value not None |
| Binary Sensor (zone) | Zone NORMAL or DEGRADED |
| Controller entities | Coordinator updated |

**Design Rationale:**
- **Climate unavailable when temp sensor fails:** Prevents "unknown" states from being recorded to history
- **Zone sensors/binary sensors unavailable during INITIALIZING:** Values not meaningful before first PID calculation
- **Zone sensors/binary sensors unavailable during FAIL_SAFE:** Zone not participating in control, values would be misleading

**Note:** Controller-level entities (mode select, requesting zones sensor, status binary sensor) remain available regardless of individual zone status.

---

## 6. Control Algorithm

### 6.1 Execution Cycle

The coordinator runs every **60 seconds** and performs:

1. **PID Update** (per zone)
2. **Historical State Query** (per zone)
3. **Zone Decision** (per zone)
4. **Heat Request Aggregation**
5. **Boiler Mode Management**

### 6.2 PID Controller

```python
class PIDController:
    def __init__(self, kp: float, ki: float, kd: float,
                 integral_min: float, integral_max: float):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral_min = integral_min
        self.integral_max = integral_max
        self.integral = 0.0
        self.last_error = 0.0

    def update(self, setpoint: float, current: float, dt: float) -> float:
        """Calculate duty cycle (0-100) from temperature error."""
        error = setpoint - current

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup
        self.integral += error * dt
        self.integral = max(self.integral_min,
                           min(self.integral_max, self.integral))
        i_term = self.ki * self.integral

        # Derivative term
        d_term = self.kd * (error - self.last_error) / dt if dt > 0 else 0
        self.last_error = error

        # Output clamped to 0-100%
        output = p_term + i_term + d_term
        return max(0.0, min(100.0, output))
```

### 6.3 PID Integration Pausing

To prevent integral windup during periods when heating is blocked or irrelevant, the PID controller's `update()` method is skipped (integration paused) when any of the following conditions are true:

| Condition | Reason |
|-----------|--------|
| Temperature unavailable | Cannot calculate meaningful error without current temperature |
| Controller mode ≠ `auto` | PID control only applies in automatic mode |
| Zone disabled | Disabled zones don't participate in heating |
| Window open (above threshold) | Heating blocked, would cause integral windup |

When paused:
- The integral term is frozen at its current value
- The duty cycle is maintained at its last calculated value
- The error term is still updated (for UI display purposes)

```python
def _should_pause_pid(self, runtime: ZoneRuntime) -> bool:
    """Check if PID integration should be paused."""
    # Only auto mode uses PID-based control
    if self._state.mode != "auto":
        return True

    # Disabled zones shouldn't accumulate integral
    if not runtime.state.enabled:
        return True

    # Window was open recently - pause PID to let temperature stabilize
    if runtime.state.window_recently_open:
        return True

    return False
```

This prevents the common problem of integral windup where the integral term accumulates while the room temperature is unstable after a window opening, which would cause overshoot when normal control resumes.

### 6.4 Time Windows

| Window | Duration | Calculation |
|--------|----------|-------------|
| **Observation Period** | 2 hours (default) | Aligned to even hours (00:00, 02:00, 04:00...) |
| **Valve Open Detection** | 3.5 minutes | Fixed window for detecting valve fully open |

**Observation Period Alignment:**
```python
def get_observation_start(now: datetime) -> datetime:
    hour = now.hour
    period_hour = hour - (hour % 2)  # Round down to even hour
    return now.replace(hour=period_hour, minute=0, second=0, microsecond=0)
```

### 6.5 Zone Decision Tree

```python
def evaluate_zone(zone: ZoneState, controller: ControllerState,
                  timing: TimingParams) -> ZoneAction:

    # Flush circuit priority during DHW heating or post-DHW flush period
    if (zone.circuit_type == "flush" and
        controller.flush_enabled and
        is_flush_requested(controller) and  # True during DHW or post-DHW period
        not any_regular_circuits_active(controller)):  # No regular valves currently ON
        return ZoneAction.TURN_ON

    # Note: Window blocking is handled via PID pause, not valve control
    # Valves follow quota-based scheduling regardless of window state

    # Near end of observation period - freeze valve positions
    time_remaining = timing.observation_period - controller.period_elapsed
    if time_remaining < timing.min_run_time:
        return ZoneAction.STAY_ON if zone.valve_on else ZoneAction.STAY_OFF

    # Quota-based scheduling
    if zone.used_duration < zone.requested_duration:
        # Zone still needs heating this period

        if zone.valve_on:
            # Already on - stay on (re-send to prevent relay timeout)
            return ZoneAction.STAY_ON

        remaining_quota = zone.requested_duration - zone.used_duration
        if remaining_quota < timing.min_run_time:
            # Not enough quota left to justify turning on
            return ZoneAction.STAY_OFF

        if controller.dhw_active and zone.circuit_type == "regular":
            # DHW priority: regular circuits that are OFF cannot turn ON
            # (valves already ON returned STAY_ON above, continuing water circulation)
            return ZoneAction.STAY_OFF

        # Turn on
        return ZoneAction.TURN_ON

    else:
        # Zone has met its quota
        if zone.valve_on:
            return ZoneAction.TURN_OFF
        return ZoneAction.STAY_OFF
```

### 6.6 Heat Request Logic

```python
def should_request_heat(zone: ZoneState, timing: TimingParams) -> bool:
    if not zone.valve_on:
        return False

    # Wait for valve to fully open
    if zone.open_state_avg < 0.85:
        return False

    # Don't request if zone is about to close
    remaining_quota = zone.requested_duration - zone.used_duration
    if remaining_quota < timing.closing_warning_duration:
        return False

    return True

def aggregate_heat_request(zones: dict[str, ZoneState],
                           timing: TimingParams) -> bool:
    return any(should_request_heat(z, timing) for z in zones.values())
```

### 6.7 Boiler Summer Mode Management

```python
def update_summer_mode(controller: ControllerState,
                       heat_request: bool,
                       summer_mode_entity: str | None):
    if summer_mode_entity is None:
        return

    if controller.mode != "auto":
        return

    if heat_request and current_summer_mode != "winter":
        # Enable boiler UFH circuit
        set_summer_mode("winter")

    elif not heat_request and current_summer_mode != "summer":
        # Disable boiler UFH circuit (saves energy)
        set_summer_mode("summer")
```

---

## 7. Operation Modes

### 7.1 Automatic Mode (`auto`)

Default mode. Full PID control with br-based scheduling.

- PID controllers update every 60 seconds
- Valves managed based on duty cycle and observation period quota
- Window blocking active
- DHW flush priority active (if configured)

### 7.2 Flush Mode (`flush`)

System maintenance mode for pipe flushing.

- All valves forced OPEN
- Boiler summer_mode set to "summer" (circulation only, no firing)
- Typically scheduled weekly (e.g., Saturday 02:00-02:30)

### 7.3 Cycle Mode (`cycle`)

Diagnostic mode that rotates through zones.

- One zone open at a time on 8-hour rotation
- Hour 0: all closed (rest)
- Hours 1-7: zones open sequentially

### 7.4 All On Mode (`all_on`)

Manual override - maximum heating.

- All valves forced OPEN
- Boiler summer_mode set to "winter"
- Heat request ON

### 7.5 All Off Mode (`all_off`)

Manual override - heating disabled.

- All valves forced CLOSED
- Boiler summer_mode set to "summer"
- Heat request OFF

### 7.6 Disabled Mode (`disabled`)

Controller inactive. No actions taken, entities remain in last state.

---

## 8. Historical State Queries

The integration uses Home Assistant's Recorder component to query historical entity states for time-windowed calculations.

### 8.1 Query Interface

```python
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period

async def get_state_average(
    hass: HomeAssistant,
    entity_id: str,
    start: datetime,
    end: datetime,
    on_value: str = "on"
) -> float:
    """Calculate average state (0.0-1.0) over time period."""
    states = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        start,
        end,
        entity_id
    )

    if not states.get(entity_id):
        return 0.0

    # Time-weighted average calculation
    total_on_time = 0.0
    total_time = (end - start).total_seconds()

    state_list = states[entity_id]
    for i, state in enumerate(state_list):
        state_start = max(state.last_changed, start)
        state_end = state_list[i + 1].last_changed if i + 1 < len(state_list) else end
        duration = (state_end - state_start).total_seconds()

        if state.state == on_value:
            total_on_time += duration

    return total_on_time / total_time if total_time > 0 else 0.0
```

### 8.2 Required Queries Per Cycle

For each zone, the coordinator queries:

| Query | Entity | Window | Purpose |
|-------|--------|--------|---------|
| Valve state average | `switch.{}` (valve) | observation_start → now | Calculate used_duration |
| Valve open average | `switch.{}` (valve) | now - 3.5min → now | Detect valve fully open |
| Window open average | `binary_sensor.{}` (windows) | observation_start → now | Window blocking decision (converted to seconds) |

Note: `requested_duration` is calculated from the current instantaneous PID duty cycle output, not a historical average.

### 8.3 Zone-Level Fault Isolation

The controller implements zone-level fault isolation to ensure that failures in one zone do not affect other zones. This is critical for multi-zone installations where individual temperature sensors or valve entities may fail independently.

#### 8.3.1 Zone Status

Each zone tracks its own operational status independently:

| Status | Description |
|--------|-------------|
| `normal` | Zone operating normally with valid temperature readings |
| `degraded` | Temperature sensor unavailable or Recorder query failing; using fallback values |
| `fail_safe` | No successful update for >1 hour; valve forced closed |

**Zone Degraded Behavior:**

When a zone enters degraded status:
- PID controller continues with last-known duty cycle
- Valve scheduling continues based on cached demand
- Climate entity shows `zone_status: degraded` in attributes
- Zone can still respond to setpoint changes

**Zone Fail-Safe Behavior:**

When a zone enters fail-safe (after 1 hour of degraded operation):
- Zone's valve is forced closed
- Zone no longer participates in heating
- Climate entity shows `zone_status: fail_safe` in attributes
- Recovery requires successful temperature reading and Recorder query

#### 8.3.2 Zone Isolation Guarantee

**Critical Requirement:** Working zones must NEVER be affected by failing zones.

| Scenario | Result |
|----------|--------|
| 1 of 7 zones fails | 6 zones continue operating indefinitely |
| 6 of 7 zones fail | 1 zone continues operating indefinitely |
| All zones fail | Controller enters fail-safe only after all zones are in fail-safe |

The controller NEVER enters fail-safe if at least one zone is operating normally.

#### 8.3.3 Recorder Query Handling

**Query Criticality (per-zone):**

| Query | Criticality | Fallback on Failure |
|-------|-------------|---------------------|
| Period state average (quota) | Critical for zone | Zone enters degraded, retains last valve state |
| Valve open average | Non-critical | Use current valve entity state |
| Window open average | Non-critical | Assume windows closed |

#### 8.3.4 Valve Entity Handling

Valve state is tracked using the `ValveState` enum with explicit uncertainty handling:

```python
class ValveState(StrEnum):
    ON = "on"           # Valve confirmed open
    OFF = "off"         # Valve confirmed closed
    UNKNOWN = "unknown" # State unknown (HA reports unknown)
    UNAVAILABLE = "unavailable"  # Entity unavailable or not found
```

**State Mapping:**

| HA Entity State | ValveState | Heat Request | Valve Command |
|-----------------|------------|--------------|---------------|
| `on` | ON | Allowed | STAY_ON |
| `off` | OFF | Blocked | Evaluate quota |
| `unknown` | UNKNOWN | Blocked | Re-send intended command |
| `unavailable` | UNAVAILABLE | Blocked | Re-send intended command |
| Entity not found | UNAVAILABLE | Blocked | Re-send intended command |

**Behavior Design:**
- **Heat request blocked**: When valve state is uncertain, boiler heat is NOT requested (conservative - don't fire boiler if we can't confirm valve is open)
- **Commands re-sent**: When state is UNKNOWN/UNAVAILABLE, the controller re-sends the intended command (turn_on or turn_off) to force synchronization
- **Warning logged**: User is notified of valve state issues via logs

**Rationale:**
- Uncertain valve state should not trigger boiler heating (safety)
- Re-sending commands helps recover from transient communication issues
- Zone continues evaluating and controlling even if state is uncertain

#### 8.3.5 Controller Status Aggregation

The controller status is derived from zone statuses:

| Condition | Controller Status |
|-----------|-------------------|
| All zones normal | `normal` |
| Any zone degraded or fail-safe, but at least one normal | `degraded` |
| All zones in fail-safe | `fail_safe` |

**Controller Status Entity:**

The `binary_sensor.{controller_id}_status` entity exposes operational status:

| Attribute | Type | Description |
|-----------|------|-------------|
| `status` | string | "normal", "degraded", or "fail_safe" |
| `zones_degraded` | int | Number of zones in degraded state |
| `zones_fail_safe` | int | Number of zones in fail-safe state |

The binary sensor is `on` (problem state) when status is degraded or fail-safe.

#### 8.3.6 Summer Mode Safety

When ANY zone is in fail-safe state:
- Summer mode is forced to "auto" permanently
- This allows physical fallback valves to receive heated water
- Controller cannot override summer mode while any zone is in fail-safe
- This ensures heating is available via physical fallback mechanisms

#### 8.3.7 Recovery

**Zone Recovery:**
- When temperature reading and Recorder queries succeed:
  - Zone status returns to "normal"
  - Zone failure counter resets to 0
  - Normal control resumes automatically

**Controller Recovery:**
- When all zones recover, controller status returns to "normal"
- Summer mode returns to automatic control when no zones are in fail-safe

### 8.4 Performance Considerations

- Queries are batched where possible
- Results are cached within each coordinator cycle
- Recorder queries run in executor to avoid blocking event loop
- Consider adding configurable history depth limit

---

## 9. Project Structure

```
hass-ufh-controller/
├── custom_components/
│   └── ufh_controller/
│       ├── __init__.py              # async_setup_entry, platform forwarding
│       ├── manifest.json            # Integration metadata
│       ├── const.py                 # DOMAIN, defaults, platform list
│       ├── config_flow.py           # ConfigFlow + OptionsFlow classes
│       ├── coordinator.py           # DataUpdateCoordinator subclass
│       ├── device.py                # DeviceInfo helpers
│       │
│       ├── platforms/
│       │   ├── __init__.py
│       │   ├── climate.py           # HeatingZoneClimate entity
│       │   ├── sensor.py            # Duty cycle, PID error, etc.
│       │   ├── binary_sensor.py     # Blocked, heat request
│       │   ├── select.py            # Controller mode selector
│       │   └── switch.py            # Heat request, flush enable
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── controller.py        # Main control loop logic
│       │   ├── zone.py              # Zone dataclass + decision logic
│       │   ├── pid.py               # PID controller class
│       │   └── history.py           # Recorder query helpers
│       │
│       ├── strings.json             # Config flow strings
│       └── translations/
│           └── en.json              # English translations
│
├── docs/
│   └── specification.md             # This specification
│
├── tests/
│   ├── conftest.py                  # Shared fixtures, mock HA setup
│   ├── unit/                        # Pure logic tests, no HA dependencies
│   │   ├── test_pid.py              # PID controller unit tests
│   │   └── test_history.py          # Recorder query helper tests
│   ├── integration/                 # Entity platform tests with mocked HA
│   │   ├── test_controller.py       # Core controller logic tests
│   │   ├── test_controller_modes.py # Mode evaluation tests
│   │   ├── test_zone_evaluation.py  # Zone decision logic tests
│   │   ├── test_zone_flush.py       # Flush circuit behavior tests
│   │   ├── test_zone_models.py      # Zone data structure tests
│   │   ├── test_climate.py          # Climate entity tests
│   │   ├── test_sensor.py           # Sensor entity tests
│   │   ├── test_binary_sensor.py    # Binary sensor tests
│   │   ├── test_select.py           # Select entity tests
│   │   └── test_switch.py           # Switch entity tests
│   ├── scenarios/                   # End-to-end workflow tests
│   │   ├── test_coordinator_persistence.py  # State save/restore
│   │   ├── test_coordinator_failure.py      # Failure recovery
│   │   ├── test_valve_sync.py               # Valve synchronization
│   │   └── test_zone_initial_state.py       # Initial startup
│   └── config/                      # Config flow tests
│       ├── test_config_flow_user.py     # Initial setup flow
│       ├── test_config_flow_options.py  # Options flow
│       ├── test_config_flow_zone.py     # Zone subentry flow
│       ├── test_init.py                 # Entry setup/unload
│       └── test_entity_unavailability.py # Conditional entities
│
├── .github/
│   └── workflows/
│       └── lint.yml                 # CI pipeline
│       └── validate.yml             # CI pipeline
│       └── checks.yml               # CI pipeline
│
├── pyproject.toml                   # Project config (uv/pip, pytest, ty, ruff)
├── README.md                        # User documentation
└── LICENSE
```

---

## 10. Testing Strategy

Tests are organized into four directories based on scope and dependencies.

### 10.1 Unit Tests (`tests/unit/`)

Pure logic tests with no Home Assistant dependencies.

**PID Controller (`test_pid.py`):**
- Proportional response to error
- Integral accumulation over time
- Integral anti-windup (clamping)
- Output clamping (0-100%)
- Derivative response (if used)

**History Helpers (`test_history.py`):**
- Observation window alignment
- State average calculations
- Recorder query error handling

### 10.2 Integration Tests (`tests/integration/`)

Component tests with mocked Home Assistant entities.

**Zone Logic (`test_zone_evaluation.py`, `test_zone_flush.py`, `test_zone_models.py`):**
- Decision tree branches (all paths)
- Window blocking threshold
- Quota calculations
- Minimum run time enforcement
- DHW priority for flush circuits
- Flush circuit post-DHW behavior

**Controller Logic (`test_controller.py`, `test_controller_modes.py`):**
- Heat request aggregation
- Mode switching behavior
- Summer mode transitions
- Flush mode valve states
- Cycle mode rotation
- PID integration pausing

**Entities (`test_climate.py`, `test_sensor.py`, `test_binary_sensor.py`, etc.):**
- Entity creation on setup
- State updates from coordinator
- Climate setpoint changes
- Mode changes
- Preset activation

### 10.3 Scenario Tests (`tests/scenarios/`)

End-to-end workflow tests for resilience and state management.

**Coordinator Persistence (`test_coordinator_persistence.py`):**
- State save on unload
- State restore on setup
- PID state preservation across restarts

**Coordinator Failure (`test_coordinator_failure.py`):**
- Database query failures
- Zone degradation states
- Fail-safe timeout behavior
- Recovery from temporary failures

**Valve Sync (`test_valve_sync.py`):**
- External interference recovery
- Unknown/unavailable valve handling

### 10.4 Config Tests (`tests/config/`)

Configuration flow and setup lifecycle tests.

**Config Flow (`test_config_flow_user.py`, `test_config_flow_options.py`, `test_config_flow_zone.py`):**
- Initial setup flow completion
- Zone addition via subentry flow
- Zone editing and deletion
- Validation errors (duplicate IDs, missing entities)
- Options flow for timing and entities

### 10.5 Test Fixtures

```python
# conftest.py
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry with subentries."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test Controller",
            "controller_id": "test",
        },
        options={},  # Options kept minimal, timing in controller subentry
        subentries_data=[
            # Controller subentry (auto-created)
            {
                "subentry_type": "controller",
                "unique_id": "controller",
                "title": "Test Controller",
                "data": {"timing": DEFAULT_TIMING},
            },
            # Zone subentry
            {
                "subentry_type": "zone",
                "unique_id": "zone1",
                "title": "Test Zone",
                "data": {
                    "id": "zone1",
                    "name": "Test Zone",
                    "circuit_type": "regular",
                    "temp_sensor": "sensor.zone1_temp",
                    "valve_switch": "switch.zone1_valve",
                    "setpoint": {"min": 18, "max": 25, "step": 0.5, "default": 21},
                    "pid": {"kp": 50, "ki": 0.05, "kd": 0,
                            "integral_min": 0, "integral_max": 100},
                    "window_sensors": [],
                    "presets": {
                        "home": 21.0,
                        "away": 16.0,
                        "eco": 19.0,
                        "comfort": 22.0,
                        "boost": 25.0,
                    },
                },
            },
        ],
    )
```

### 10.4 Coverage Target

- **Overall Minimum**: 90% line coverage (enforced in pyproject.toml and CI)
- **Core Modules Target**: 98%+ for core/ modules (critical control logic)
- **Current**: 92.81% overall coverage (exceeds minimum)
  - `core/controller.py`: 99%
  - `core/history.py`: 100%
  - `core/pid.py`: 100%
  - `core/zone.py`: 98%

Coverage is measured using pytest-cov and reported in XML format to Codecov for tracking.

---

## 11. CI/CD Pipeline

### 11.1 GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Run tests with coverage
        run: uv run pytest --cov=custom_components/ufh_controller --cov-report=xml --cov-report=term

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v5
        with:
          token: ${{ secrets.CODECOV_TOKEN }}
          files: ./coverage.xml
          fail_ci_if_error: true

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Ruff check
        run: uv run ruff check .

      - name: Ruff format check
        run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Type check
        run: uv run ty check .
```

### 11.2 Pre-commit Hooks (Optional)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

---

## 12. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Recorder queries slow | Control loop delayed | Medium | Batch queries, cache results, set timeout |
| Recorder queries fail | Control loop blocked, valves stuck | Medium | Graceful degradation with fallbacks (see §8.3) |
| HA restart loses state | Observation period resets, valves may cycle | Low | Recalculate from Recorder history on startup |
| PID integral windup | Overshoot after blocked period | Medium | PID integration paused when zone blocked (see §6.3) |
| Valve rapid cycling | Wear, inefficiency | Low | Enforce minimum run time, hysteresis |
| Sensor unavailable | Zone can't control | Medium | PID paused, duty cycle maintained (see §6.3) |
| Config migration | Breaking changes on update | Low | Version config schema, write migration code |

---

## 13. Configuration Reference

This section provides detailed documentation for all configuration parameters in the Underfloor Heating Controller. Each parameter directly affects how the heating system operates.

### 13.1 Timing Parameters

Timing parameters control the scheduling, valve operation, and observation windows used by the controller. All values are in seconds unless otherwise noted.

#### observation_period

**Default:** 7200 seconds (2 hours)
**Range:** 1800-14400 seconds (30 minutes to 4 hours)
**Config location:** Controller subentry → `data.timing.observation_period`

The observation period defines the time window used for quota-based valve scheduling. Each zone is allocated a "quota" of valve-on time based on its PID-calculated duty cycle, and this quota is distributed across the observation period.

**How it works:** Observation periods are aligned to even hours (00:00, 02:00, 04:00, etc.). When an observation period ends, a new one begins and all zone quotas reset. The controller calculates how much time each zone's valve has been open during the current period (`used_duration`) and compares it to how much time it should be open (`requested_duration = duty_cycle% × observation_period`).

**Examples:**
- With a 2-hour (7200s) observation period and a zone duty cycle of 50%, the zone's valve should be open for 3600 seconds (1 hour) during that period.
- If a zone has been on for 2000 seconds already and needs 3600 total, it still has 1600 seconds of quota remaining and will be allowed to turn on again.

**Why it matters:** Shorter periods allow more responsive heating but may cause more valve cycling. Longer periods reduce valve wear but make the system less responsive to temperature changes.

#### min_run_time

**Default:** 540 seconds (9 minutes)
**Range:** 60-1800 seconds (1 to 30 minutes)
**Config location:** Controller subentry → `data.timing.min_run_time`

The minimum meaningful duration for a valve state change. This parameter serves two purposes:

1. **Prevents short valve runs:** Before turning ON a valve, the controller checks if the zone's remaining quota is at least `min_run_time`. If not, the valve stays off rather than doing a brief run.

2. **Prevents end-of-period cycling:** When the time remaining in the observation period is less than `min_run_time`, valve positions are frozen. This prevents unnecessary cycling at period boundaries (e.g., turning off a valve only to turn it back on when the new period starts moments later).

**How it works:** The controller applies two checks using this parameter:
- Before turning ON: `remaining_quota >= min_run_time`
- Before any change: `time_remaining_in_period >= min_run_time`

If either check fails, the valve maintains its current state.

**Examples:**
- Zone has used 6700s of a 7200s quota (500s remaining). With `min_run_time=540s`, the valve won't turn on because 500 < 540.
- Zone has used 0s of a 3600s quota (3600s remaining). With `min_run_time=540s`, the valve can turn on because 3600 > 540.
- 5 minutes remain in the observation period and a zone's quota is met. With `min_run_time=540s` (9 min), the valve stays in its current state rather than turning off, since the new period would likely turn it back on anyway.

**Why it matters:** Too low causes valve wear from frequent switching. Too high prevents zones from using their full quota in small increments and extends the freeze period at observation boundaries.

#### valve_open_time

**Default:** 210 seconds (3.5 minutes)
**Range:** 60-600 seconds (1 to 10 minutes)
**Config location:** Controller subentry → `data.timing.valve_open_time`

The time window used to detect when a valve is fully open before requesting heat from the boiler.

**How it works:** The controller queries the valve's historical state over the last `valve_open_time` seconds. If the valve has been on for at least 85% of that window (`open_state_avg ≥ 0.85`), it's considered fully open and can contribute to the heat request. This prevents firing the boiler before water can flow through the zone.

**Examples:**
- Valve turned on 4 minutes ago. With `valve_open_time=210s`, the controller checks the last 210 seconds and finds the valve was on for 100% of that time. The zone requests heat.
- Valve just turned on 30 seconds ago. With `valve_open_time=210s`, the controller only sees 30 seconds of on-time, which is < 85% of 210 seconds. The zone doesn't request heat yet.

**Why it matters:** Too short risks firing the boiler before valves are open, wasting energy. Too long delays heat delivery and reduces comfort.

#### closing_warning_duration

**Default:** 240 seconds (4 minutes)
**Range:** 60-600 seconds (1 to 10 minutes)
**Config location:** Controller subentry → `data.timing.closing_warning_duration`

The minimum quota remaining before a zone stops requesting heat from the boiler, even if the valve is still open.

**How it works:** When a zone has less than `closing_warning_duration` seconds of quota remaining, it stops contributing to the heat request signal. This gives the boiler advance notice that the zone is about to close, preventing short heating cycles.

**Examples:**
- Zone has 1000s quota, used 800s, leaving 200s remaining. With `closing_warning_duration=240s`, the zone stops requesting heat because 200 < 240, even though the valve stays open.
- Zone has 3600s quota, used 3000s, leaving 600s remaining. With `closing_warning_duration=240s`, the zone continues requesting heat because 600 > 240.

**Why it matters:** Prevents the boiler from firing up shortly before a valve closes, which wastes energy and causes inefficient cycling.

#### window_block_time

**Default:** 600 seconds (10 minutes)
**Range:** 0-3600 seconds (0 to 60 minutes)
**Config location:** Controller subentry → `data.timing.window_block_time`

The time period after a window closes during which PID control remains paused to allow room temperature to stabilize.

**How it works:** The controller checks if any window sensor was open within the last `window_block_time` seconds. If so, PID controller updates are paused but the valve maintains its last calculated duty cycle. This allows the room temperature to stabilize naturally after a window opening without the PID controller reacting to temporary temperature fluctuations. Once `window_block_time` seconds have passed since all windows were last open, PID control resumes.

**Examples:**
- Window opens at 14:00 and closes at 14:05 (5 minutes open). With `window_block_time=600s`, PID is paused from 14:00 until 14:15 (10 minutes after the window closed). At 14:15, PID control resumes.
- Window is currently open → PID remains paused, valve maintains last duty cycle.
- Window closed 15 minutes ago → PID control is active, valve follows quota-based scheduling.

**Why it matters:** For underfloor heating systems, pausing PID control rather than closing valves is more effective. The high thermal mass means temperature changes slowly, so letting the system stabilize naturally produces better control than immediate reactions. Setting to 0 disables window blocking entirely.

#### controller_loop_interval

**Default:** 60 seconds
**Range:** 10-300 seconds
**Config location:** Controller subentry → `data.timing.controller_loop_interval`

The interval at which the coordinator runs the control loop, updating PID controllers and making valve decisions.

**How it works:** Every `controller_loop_interval` seconds, the coordinator:
1. Updates each zone's PID controller with the latest temperature
2. Queries historical state from the recorder
3. Evaluates zone decisions
4. Aggregates heat request
5. Updates all entities

**Examples:**
- With `controller_loop_interval=60s`, the PID controller receives updates every minute, and `dt=60` in the PID calculations.
- With `controller_loop_interval=30s`, updates happen twice as often with `dt=30`.

**Why it matters:** Shorter intervals provide more responsive control but increase database load from recorder queries. Longer intervals reduce load but make the system less responsive. 60 seconds is a good balance for residential heating.

#### flush_duration

**Default:** 480 seconds (8 minutes)
**Range:** 0-1800 seconds (0 to 30 minutes)
**Config location:** Controller subentry → `data.timing.flush_duration`

The duration to continue flush circuit operation after DHW heating ends.

**How it works:** When DHW heating completes (DHW sensor transitions from ON to OFF) and `flush_enabled` is on, flush circuits continue operating for `flush_duration` seconds to capture residual heat from the DHW tank and pipes. Set to 0 to disable post-DHW flushing (flush circuits will only operate while DHW is actively heating).

**Examples:**
- With `flush_duration=480s` (8 minutes): After DHW heating stops, flush circuits remain active for 8 more minutes to capture residual heat.
- With `flush_duration=0s`: Flush circuits only operate while DHW is actively heating, stopping immediately when DHW completes.

**Why it matters:** DHW tanks and pipes retain heat after the heating cycle completes. This residual heat would otherwise be wasted. By continuing flush circuit operation for a period after DHW ends, you can capture this latent heat and distribute it to flush-type zones (typically bathrooms), improving energy efficiency.

---

### 13.2 PID Parameters

PID parameters control the temperature regulation algorithm for each zone. These are configured per-zone and affect how aggressively the system responds to temperature errors.

#### kp (Proportional Gain)

**Default:** 50.0
**Range:** Any positive float (typically 1.0-200.0)
**Config location:** Zone subentry → `data.pid.kp`

The proportional gain determines the immediate response to temperature error. Higher values create stronger responses to temperature deviations.

**How it works:** The proportional term is calculated as `p_term = kp × error`, where `error = setpoint - current_temperature`. If the room is 2°C below setpoint and `kp=50`, then `p_term = 50 × 2 = 100%` duty cycle (clamped to 100%).

**Examples:**
- Room at 20°C, setpoint 21°C, `kp=50`: `p_term = 50 × 1 = 50%` duty cycle.
- Room at 19°C, setpoint 21°C, `kp=50`: `p_term = 50 × 2 = 100%` duty cycle.
- Room at 20.5°C, setpoint 21°C, `kp=50`: `p_term = 50 × 0.5 = 25%` duty cycle.
- Same conditions with `kp=100`: `p_term = 100 × 0.5 = 50%` duty cycle (more aggressive).

**Why it matters:** Too low results in slow temperature recovery. Too high causes oscillation around the setpoint. For hydronic heating with slow thermal response, 50.0 is a good starting point.

#### ki (Integral Gain)

**Default:** 0.001
**Range:** Any positive float (typically 0.0001-0.01)
**Config location:** Zone subentry → `data.pid.ki`

The integral gain determines how past temperature errors accumulate to eliminate steady-state error. The integral term grows over time when temperature remains below setpoint.

**How it works:** The integral accumulates as `integral += ki × error × dt` (in % units). With `ki=0.001`, `error=1°C`, and `dt=60s`, the integral increases by `0.001 × 1 × 60 = 0.06%` per control cycle. Over time, this adds up to eliminate persistent errors.

**Examples:**
- Room stuck at 20.5°C, setpoint 21°C (error = 0.5°C), `ki=0.001`, `dt=60s`:
  - After 1 minute: `integral += 0.001 × 0.5 × 60 = 0.03%`
  - After 10 minutes: `integral ≈ 0.3%` (accumulated)
  - After 1 hour: `integral ≈ 1.8%` (accumulated)
- With higher `ki=0.01`, the same scenario accumulates 10× faster, reaching 18% after 1 hour.

**Why it matters:** The integral term ensures the room eventually reaches the exact setpoint even if the proportional term alone isn't enough. Too low and the room never quite reaches setpoint. Too high causes overshoot and oscillation. The default `0.001` provides gentle long-term correction.

**Special note:** The integral is stored in percentage units (not raw error-seconds), so changing `ki` doesn't immediately affect the accumulated contribution—only future accumulation rates change.

#### kd (Derivative Gain)

**Default:** 0.0
**Range:** Any positive float (typically 0.0-10.0)
**Config location:** Zone subentry → `data.pid.kd`

The derivative gain responds to the rate of change of temperature error, providing damping against oscillations.

**How it works:** The derivative term is calculated as `d_term = kd × (error - last_error) / dt`. If temperature is changing rapidly, the derivative term adjusts the output to slow the approach to setpoint.

**Examples:**
- Error changed from 1.0°C to 0.5°C in 60 seconds, `kd=10`:
  - `d_term = 10 × (0.5 - 1.0) / 60 = -0.083%` (negative because error is decreasing)
- Error changed from 0.5°C to 2.0°C in 60 seconds, `kd=10`:
  - `d_term = 10 × (2.0 - 0.5) / 60 = 0.25%` (positive because error is increasing)

**Why it matters:** Derivative control can reduce overshoot and oscillation in fast-responding systems. However, hydronic heating systems are very slow and derivative control often adds noise rather than improvement. The default `kd=0.0` disables derivative control, which is appropriate for most UFH systems.

#### integral_min

**Default:** 0.0
**Range:** Any float (typically -100.0 to 0.0)
**Config location:** Zone subentry → `data.pid.integral_min`

The minimum allowed value for the integral term in percentage units. This prevents integral windup in the negative direction.

**How it works:** After each PID update, the integral is clamped: `integral = max(integral_min, min(integral_max, integral))`. Since heating systems can only add heat (not cool), negative integral values are typically not useful.

**Examples:**
- Room at 22°C, setpoint 21°C (error = -1°C). With `integral_min=0.0`, the integral cannot go below 0%, preventing negative accumulation.
- With `integral_min=-50.0`, the integral could accumulate to -50% before clamping, allowing future overcooling to be "remembered."

**Why it matters:** For heating-only systems, `integral_min=0.0` is correct since we can't cool the room. For systems with both heating and cooling, you might use negative values.

#### integral_max

**Default:** 100.0
**Range:** Any positive float (typically 50.0-200.0)
**Config location:** Zone subentry → `data.pid.integral_max`

The maximum allowed value for the integral term in percentage units. This prevents integral windup when heating is blocked or ineffective.

**How it works:** The integral is clamped to this maximum, preventing unbounded accumulation when the room can't reach setpoint (e.g., when it's very cold outside or heating capacity is insufficient).

**Examples:**
- Room stuck at 19°C, setpoint 21°C. Integral keeps accumulating but stops at `integral_max=100%`.
- When the room finally warms up, the integral doesn't cause massive overshoot because it was limited to 100%.

**Why it matters:** Prevents "integral windup" where prolonged errors cause the integral term to grow excessively, leading to overshoot when conditions change. 100% is a safe limit for most systems.

---

### 13.3 Setpoint Parameters

Setpoint parameters define the allowed temperature range and precision for each zone's target temperature.

#### setpoint_min

**Default:** 16.0°C
**Range:** 5.0-30.0°C
**Config location:** Zone subentry → `data.setpoint.min`

The minimum allowed setpoint temperature for the zone climate entity.

**How it works:** Users cannot set the target temperature below this value in the Home Assistant UI. The controller also clamps any setpoint changes to this minimum.

**Examples:**
- With `setpoint_min=16.0`, the climate entity's temperature slider starts at 16°C.
- User tries to set 14°C via an automation → controller clamps to 16°C.

**Why it matters:** Prevents accidentally setting temperatures too low, which could risk pipe freezing or excessive energy waste when recovering.

#### setpoint_max

**Default:** 28.0°C
**Range:** 5.0-35.0°C
**Config location:** Zone subentry → `data.setpoint.max`

The maximum allowed setpoint temperature for the zone climate entity.

**How it works:** Users cannot set the target temperature above this value. The controller clamps any setpoint changes to this maximum.

**Examples:**
- With `setpoint_max=28.0`, the climate entity's temperature slider ends at 28°C.
- User tries to set 30°C via an automation → controller clamps to 28°C.

**Why it matters:** Prevents overheating rooms and excessive energy use. Also protects against misconfiguration or automation errors.

#### setpoint_step

**Default:** 0.5°C
**Range:** 0.1-1.0°C (from UI constraints)
**Config location:** Zone subentry → `data.setpoint.step`

The increment size for setpoint adjustments in the Home Assistant UI.

**How it works:** Defines the granularity of the temperature slider and up/down buttons in the climate entity UI.

**Examples:**
- With `step=0.5`, the slider allows 16.0°C, 16.5°C, 17.0°C, etc.
- With `step=0.1`, the slider allows finer control: 16.0°C, 16.1°C, 16.2°C, etc.

**Why it matters:** Finer steps (0.1°C) allow more precise control but may be unnecessarily granular for slow-responding hydronic systems. 0.5°C is a practical compromise.

#### setpoint_default

**Default:** 21.0°C
**Range:** 5.0-35.0°C
**Config location:** Zone subentry → `data.setpoint.default`

The initial target temperature when the zone is first created or reset.

**How it works:** This is the setpoint value used when the climate entity is first set up. It should fall between `setpoint_min` and `setpoint_max`.

**Examples:**
- New zone created with `setpoint_default=21.0` → climate entity starts at 21°C.
- Zone typically uses preset modes → `setpoint_default` is only used until first preset is selected.

**Why it matters:** Sets a sensible starting point for new zones. Usually matches the "home" or "comfort" preset temperature.

---

### 13.4 Preset Temperatures

Preset temperatures provide quick access to common temperature settings. Users can switch between presets in the climate entity UI instead of manually adjusting the setpoint.

#### home

**Default:** 21.0°C
**Config location:** Zone subentry → `data.presets.home`

Standard comfort temperature when occupants are home and active.

**Example:** User arrives home, switches climate entity to "Home" preset → setpoint changes to 21°C.

#### away

**Default:** 16.0°C
**Config location:** Zone subentry → `data.presets.away`

Energy-saving temperature when the home is unoccupied for extended periods (vacation, work trips).

**Example:** User leaves for a week, switches to "Away" preset → setpoint drops to 16°C, saving energy while preventing pipe freezing.

#### eco

**Default:** 19.0°C
**Config location:** Zone subentry → `data.presets.eco`

Moderate energy-saving temperature for daily use when comfort can be slightly reduced.

**Example:** Overnight or during the workday, switch to "Eco" preset → setpoint at 19°C reduces energy use while maintaining basic comfort.

#### comfort

**Default:** 22.0°C
**Config location:** Zone subentry → `data.presets.comfort`

Higher comfort temperature for maximum coziness.

**Example:** Cold winter evening, switch to "Comfort" preset → setpoint increases to 22°C for extra warmth.

#### boost

**Default:** 25.0°C
**Config location:** Zone subentry → `data.presets.boost`

Maximum temperature for rapid heating or special situations.

**Example:** Bathroom zone needs extra warmth, switch to "Boost" preset → setpoint jumps to 25°C for quick warmth, then returns to normal.

**Note:** All presets are optional. If not configured during zone setup, preset support is disabled and users control temperature via the setpoint slider only.

---

### 13.5 Controller-Level Configuration

These parameters are configured once for the entire controller during initial setup.

#### heat_request_entity

**Type:** Switch entity
**Required:** No
**Config location:** ConfigEntry → `data.heat_request_entity`

A switch entity that signals the boiler to provide heat. When zones request heat, this switch is turned on. When no zones need heat, it's turned off.

**How it works:** The controller aggregates heat requests from all zones and sets this switch accordingly. Typically connected to a relay or smart switch controlling the boiler's heat request input.

**Example:** `switch.boiler_heat_request` → When any zone valve is fully open and requesting heat, this switch turns on, telling the boiler to fire.

**Why it matters:** Allows the controller to manage boiler firing. If not configured, the boiler must remain in a mode where it's always ready to provide heat.

#### dhw_active_entity

**Type:** Binary sensor entity
**Required:** No
**Config location:** ConfigEntry → `data.dhw_active_entity`

A binary sensor indicating when the boiler is heating domestic hot water (DHW).

**How it works:** When this sensor is "on", DHW priority is activated:

- **Regular circuits already ON**: Continue running (STAY_ON). This allows existing heating to continue circulating water through the floor, maintaining heat distribution even though no new heat is being added.
- **Regular circuits currently OFF**: Cannot turn ON (STAY_OFF). New heating cycles are blocked until DHW completes.
- **Flush circuits**: Can capture latent heat if flush mode is enabled and no regular circuits are currently running (valve ON).

**Example:** `binary_sensor.boiler_tapwater_active` → When DHW heating starts, this turns on. Regular zones that were already heating continue to circulate water, but zones that were off wait until DHW finishes.

**Why it matters:** Prevents new heating demands from competing with DHW heating, which typically has priority. Allowing existing valves to stay open enables continued water circulation through the thermal mass of the floor, providing some heat distribution even during DHW priority. Also enables flush circuits to capture waste heat.

#### circulation_entity

**Type:** Binary sensor entity
**Required:** No
**Config location:** ConfigEntry → `data.circulation_entity`

A binary sensor indicating when the boiler's circulation pump is running.

**How it works:** Currently informational; may be used in future features for detecting flow/no-flow conditions.

**Example:** `binary_sensor.boiler_circulation` → Indicates water is circulating through the heating system.

#### summer_mode_entity

**Type:** Select entity
**Required:** No
**Config location:** ConfigEntry → `data.summer_mode_entity`

A select entity on the boiler to toggle between "summer" (heating circuit disabled, DHW only) and "winter" (heating circuit enabled) modes.

**How it works:** The controller automatically sets this to "winter" when heat is needed and "summer" when no heat is needed, saving energy by disabling the heating circuit when not in use.

**Example:** `select.boiler_summer_mode` → Set to "winter" when zones request heat, "summer" when idle.

**Why it matters:** Reduces standby energy consumption by disabling the heating circuit when not needed. Alternative to using `heat_request_entity`.

---

## Appendix A: Default Values

```python
DEFAULT_TIMING = {
    "observation_period": 7200,      # 2 hours
    "min_run_time": 540,             # 9 minutes
    "valve_open_time": 210,          # 3.5 minutes
    "closing_warning_duration": 240, # 4 minutes
    "window_block_time": 600,        # 10 minutes
}

DEFAULT_PID = {
    "kp": 50.0,
    "ki": 0.001,
    "kd": 0.0,
    "integral_min": 0.0,
    "integral_max": 100.0,
}

DEFAULT_SETPOINT = {
    "min": 16.0,
    "max": 28.0,
    "step": 0.5,
    "default": 21.0,
}

CONTROLLER_LOOP_INTERVAL = 60  # seconds
```

---

## Appendix B: Entity State Examples

### Climate Entity State

```yaml
state: heat
attributes:
  hvac_modes: [heat, off]
  min_temp: 18
  max_temp: 25
  target_temp_step: 0.5
  current_temperature: 20.3
  temperature: 22.0
  preset_mode: comfort
  preset_modes: [comfort, eco, away, boost]
  friendly_name: Living Room
  supported_features: 401  # TARGET_TEMPERATURE | PRESET_MODE | TURN_ON | TURN_OFF
```

### Controller Mode Select State

```yaml
state: auto
attributes:
  options: [auto, flush, cycle, all_on, all_off, disabled]
  friendly_name: Heating Mode
```
