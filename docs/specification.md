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
                "duty_cycle_window": 3600,     # seconds (1 hour)
                "min_run_time": 540,           # seconds (9 minutes)
                "valve_open_time": 210,        # seconds (3.5 minutes)
                "closing_warning_duration": 240, # seconds (4 minutes)
                "window_block_threshold": 0.05 # 5% average triggers block
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
                "ki": 0.05,
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
    window_open_avg: float     # Average over duty_cycle_window

    # Derived
    used_duration: float       # Seconds valve was on this period
    requested_duration: float  # Seconds valve should be on this period
    is_window_blocked: bool
    is_requesting_heat: bool

@dataclass
class ControllerState:
    mode: str  # auto, flush, cycle, all_on, all_off, disabled
    observation_start: datetime
    heat_request: bool
    flush_enabled: bool
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
- Navigate to: Settings → Devices & Services → UFH Controller → "+ Add Heating Zone"
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

Accessed via: Settings → Devices & Services → UFH Controller → Configure

The options flow provides access to **timing parameters** that apply to the entire controller:

| Field | Type | Description |
|-------|------|-------------|
| observation_period | number (s) | Time window for quota-based scheduling (default: 7200s / 2h) |
| duty_cycle_window | number (s) | Rolling window for duty cycle calculation (default: 3600s / 1h) |
| min_run_time | number (s) | Minimum valve on duration (default: 540s / 9min) |
| valve_open_time | number (s) | Time to detect valve fully open (default: 210s / 3.5min) |
| closing_warning_duration | number (s) | Warning before valve closes (default: 240s / 4min) |
| window_block_threshold | number (0-1) | Window open ratio to trigger blocking (default: 0.05 / 5%) |

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
| switch | `switch.{controller_id}_flush_enabled`     | "{name} Flush Enabled"     | DHW latent heat capture toggle |
| sensor | `sensor.{controller_id}_requesting_zones`  | "{name} Requesting Zones"  | Count of zones currently requesting heat |

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
| binary_sensor | `binary_sensor.{controller_id}_{zone_id}_blocked` | "{zone_name} Blocked" | Zone heating blocked (window open, etc.) |
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

    # Window open blocks heating - don't accumulate integral
    if runtime.state.window_open_avg > self.config.timing.window_block_threshold:
        return True

    return False
```

This prevents the common problem of integral windup where the integral term accumulates during blocked periods and causes overshoot when heating resumes.

### 6.4 Time Windows

| Window | Duration | Calculation |
|--------|----------|-------------|
| **Observation Period** | 2 hours (default) | Aligned to even hours (00:00, 02:00, 04:00...) |
| **Duty Cycle Window** | 1 hour (default) | Rolling window centered on current time |
| **Valve Open Detection** | 3.5 minutes | Fixed window for detecting valve fully open |

**Observation Period Alignment:**
```python
def get_observation_start(now: datetime) -> datetime:
    hour = now.hour
    period_hour = hour - (hour % 2)  # Round down to even hour
    return now.replace(hour=period_hour, minute=0, second=0, microsecond=0)
```

**Duty Cycle Window:**
```python
def get_duty_cycle_window(now: datetime) -> tuple[datetime, datetime]:
    if now.minute < 30:
        start = now - timedelta(hours=1)
        end = now
    else:
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=30)
    return (start, end)
```

### 6.5 Zone Decision Tree

```python
def evaluate_zone(zone: ZoneState, controller: ControllerState,
                  timing: TimingParams) -> ZoneAction:

    # Flush circuit priority during DHW heating
    if (zone.circuit_type == "flush" and
        controller.flush_enabled and
        controller.dhw_active and
        not any_regular_circuits_enabled(controller)):
        return ZoneAction.TURN_ON

    # Window blocking
    if zone.window_open_avg > timing.window_block_threshold:
        return ZoneAction.TURN_OFF

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
            # Wait for DHW heating to finish
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
| Window open average | `binary_sensor.{}` (windows) | duty_cycle_window | Window blocking decision |

Note: `requested_duration` is calculated from the current instantaneous PID duty cycle output, not a historical average.

### 8.3 Performance Considerations

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
│   ├── __init__.py
│   ├── conftest.py                  # Fixtures, mock HA setup
│   ├── test_pid.py                  # PID controller unit tests
│   ├── test_zone.py                 # Zone decision logic tests
│   ├── test_controller.py           # Aggregation, mode tests
│   ├── test_history.py              # Recorder query tests
│   ├── test_config_flow.py          # Config flow integration tests
│   ├── test_climate.py              # Climate entity tests
│   └── test_coordinator.py          # Full coordinator tests
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

### 10.1 Unit Tests

**PID Controller (`test_pid.py`):**
- Proportional response to error
- Integral accumulation over time
- Integral anti-windup (clamping)
- Output clamping (0-100%)
- Derivative response (if used)

**Zone Logic (`test_zone.py`):**
- Decision tree branches (all paths)
- Window blocking threshold
- Quota calculations
- Minimum run time enforcement
- DHW priority for flush circuits

**Controller Logic (`test_controller.py`):**
- Heat request aggregation
- Mode switching behavior
- Summer mode transitions
- Flush mode valve states
- Cycle mode rotation

### 10.2 Integration Tests

**Config Flow (`test_config_flow.py`):**
- Initial setup flow completion
- Zone addition via options flow
- Zone editing and deletion
- Validation errors (duplicate IDs, missing entities)
- Entity selector filtering

**Entities (`test_climate.py`, etc.):**
- Entity creation on setup
- State updates from coordinator
- Climate setpoint changes
- Mode changes
- Preset activation

**Coordinator (`test_coordinator.py`):**
- Full control cycle execution
- Recorder query mocking
- State persistence across updates
- Error handling (unavailable sensors)

### 10.3 Test Fixtures

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

- **Minimum**: 80% line coverage
- **Goal**: 90%+ for core/ modules

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
        run: uv run pytest --cov=custom_components/ufh_controller --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4

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
| HA restart loses state | Observation period resets, valves may cycle | Low | Recalculate from Recorder history on startup |
| PID integral windup | Overshoot after blocked period | Medium | PID integration paused when zone blocked (see §6.3) |
| Valve rapid cycling | Wear, inefficiency | Low | Enforce minimum run time, hysteresis |
| Sensor unavailable | Zone can't control | Medium | PID paused, duty cycle maintained (see §6.3) |
| Config migration | Breaking changes on update | Low | Version config schema, write migration code |

---

## Appendix A: Default Values

```python
DEFAULT_TIMING = {
    "observation_period": 7200,      # 2 hours
    "duty_cycle_window": 3600,       # 1 hour
    "min_run_time": 540,             # 9 minutes
    "valve_open_time": 210,          # 3.5 minutes
    "closing_warning_duration": 240, # 4 minutes
    "window_block_threshold": 0.05,  # 5%
}

DEFAULT_PID = {
    "kp": 50.0,
    "ki": 0.05,
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
