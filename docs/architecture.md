# Architecture

This document describes the layered architecture of the UFH Controller and the responsibilities of each component.

## Layer Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         COORDINATOR                                     │
│  (UFHControllerDataUpdateCoordinator)                                   │
│                                                                         │
│  Responsibility: Home Assistant Integration Layer                       │
│                                                                         │
│  - Read HA entity states (temperatures, valves, windows)                │
│  - Query Recorder for historical data                                   │
│  - Execute HA service calls (switch, select)                            │
│  - Manage storage persistence                                           │
│  - Pass raw data to Controller, get actions back                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CONTROLLER                                      │
│  (HeatingController)                                                    │
│                                                                         │
│  Responsibility: Pure Decision Engine                                   │
│                                                                         │
│  - Hold global config and state (mode, timing, DHW, flush)              │
│  - evaluate() returns ALL actions (valves, heat_request, summer_mode)   │
│  - Handle mode logic that spans zones (cycle mode ordering)             │
│  - Aggregate zone states into controller-level decisions                │
│  - No side effects - coordinator executes returned actions              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         ZONE                                            │
│  (ZoneRuntime + pure functions)                                         │
│                                                                         │
│  Responsibility: Single Zone Control                                    │
│                                                                         │
│  ZoneRuntime (mutable state holder):                                    │
│  - Own its config, state, and PID controller                            │
│  - update_temperature(raw_temp, dt) - apply EMA smoothing               │
│  - update_pid(dt, mode) - update PID controller                         │
│  - update_historical(period_avg, open_avg, window_open, elapsed)        │
│  - update_failure_state(now, temp_unavailable, recorder_failure)        │
│  - set_setpoint(), set_enabled() - property setters with validation     │
│                                                                         │
│  Pure functions (called by controller):                                 │
│  - evaluate_zone(runtime, controller_state, timing) → ZoneAction        │
│  - should_request_heat(runtime, timing) → bool                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Update Cycle

Each coordinator update cycle follows this flow:

```
Coordinator._async_update_data()
    │
    ├─► Update observation period (observation_start, period_elapsed)
    │
    ├─► Update DHW state from HA entity
    │
    ├─► For each zone:
    │       │
    │       ├─► Read raw temperature from HA
    │       │
    │       ├─► zone.update_temperature(raw_temp, dt)
    │       │       └─► Apply EMA smoothing
    │       │
    │       ├─► zone.update_pid(dt, mode)
    │       │       └─► Update PID if not paused
    │       │
    │       ├─► Query Recorder for historical averages
    │       │
    │       ├─► zone.update_historical(period_avg, open_avg, ...)
    │       │       └─► Calculate used/requested durations
    │       │
    │       ├─► Sync valve state from HA entity
    │       │
    │       └─► zone.update_failure_state(now, temp_unavail, recorder_fail)
    │               └─► Track zone status (normal/degraded/fail_safe)
    │
    ├─► controller.evaluate(now) → ControllerActions
    │       │
    │       ├─► Evaluate regular zones first
    │       ├─► Compute flush_request
    │       ├─► Evaluate flush zones
    │       ├─► Compute heat_request action (if changed)
    │       └─► Compute summer_mode action (if changed)
    │
    ├─► Execute returned actions:
    │       ├─► Valve actions via switch services
    │       ├─► Heat request via switch service (if present)
    │       └─► Summer mode via select service (if present)
    │
    └─► Save state to storage
```

### Controller Actions

The controller's `evaluate()` method returns a `ControllerActions` dataclass containing all decisions:

```python
@dataclass
class ControllerActions:
    """All actions computed by the controller for execution."""

    valve_actions: dict[str, ZoneAction]  # zone_id → action
    heat_request: ValveState | None       # ON/OFF, or None if no change
    summer_mode: SummerMode | None        # winter/summer/auto, or None if no change
```

This design enables:
- **Pure function testing**: Call `evaluate()` with known state, assert on returned actions
- **Clear separation**: Controller decides, coordinator executes
- **Minimal actions**: Only returns actions when state change is needed
- **Single decision point**: All control logic evaluated together

### Zone Update Stages

Zone updates happen in distinct stages. The first four are called by the coordinator to update zone state; the fifth is called by the controller during `evaluate()`:

| Stage | Function | Called By | Purpose |
|-------|----------|-----------|---------|
| 1. Temperature | `zone.update_temperature()` | Coordinator | Apply EMA smoothing to raw sensor reading |
| 2. PID | `zone.update_pid()` | Coordinator | Calculate duty cycle (paused when blocked) |
| 3. Historical | `zone.update_historical()` | Coordinator | Update averages and calculate quota usage |
| 4. Failure | `zone.update_failure_state()` | Coordinator | Track zone health status |
| 5. Evaluate | `evaluate_zone()` | Controller | Determine valve action (pure function) |

## Component Responsibilities

### Coordinator

The coordinator is the **only** component that interacts with Home Assistant:

- **Entity State Reading**: Temperature sensors, valve switches, window sensors
- **Recorder Queries**: Historical valve state averages
- **Service Calls**: Switch turn_on/turn_off, select select_option
- **Storage**: Persist state for crash resilience

The coordinator should **not** contain business logic. It transforms HA data into the format expected by the controller and zones.

### Controller

The controller is a **pure decision engine** with no side effects:

- **Global State**: Operation mode, DHW active, flush state
- **Single Entry Point**: `evaluate()` computes all actions at once
- **Aggregation**: Combines zone evaluations into `ControllerActions`
- **Mode Handling**: Implements mode-specific behavior (cycle, flush, all_on, etc.)

The controller should **not** contain single-zone logic. If a method takes `zone_id` as a parameter and only operates on that zone, it belongs in the Zone class.

The controller should **not** execute actions. It returns `ControllerActions` and the coordinator executes them.

### Zone (ZoneRuntime + Pure Functions)

The zone layer manages **single-zone** state and decisions, split into two parts:

**ZoneRuntime** (mutable state holder):
- **State Ownership**: Temperature, setpoint, valve state, PID state
- **Temperature Processing**: EMA smoothing via `update_temperature()`
- **PID Control**: Update PID controller via `update_pid()`, handle pause conditions
- **Historical Tracking**: Used duration, requested duration via `update_historical()`
- **Failure Isolation**: Track zone-specific failures via `update_failure_state()`

**Pure Functions** (side-effect free, called by controller):
- **`evaluate_zone()`**: Determine valve action based on quota and state
- **`should_request_heat()`**: Determine if zone should request heat from boiler

This separation ensures decision logic is testable without mocking state updates. Zones are **self-contained** - they receive inputs and produce outputs without knowing about other zones or Home Assistant.

## Design Principles

### 1. Single Responsibility

Each layer has one job:
- Coordinator: HA integration
- Controller: Multi-zone orchestration
- Zone: Single-zone control

### 2. Dependency Direction

Dependencies flow downward:
- Coordinator depends on Controller, Zone, Recorder (HA-specific)
- Controller depends on Zone (ZoneRuntime + pure functions)
- Zone depends on PID, EMA (pure utilities)
- PID, EMA, History depend on nothing (stdlib only)

### 3. Testability

- **PID, EMA, History**: Unit testable, no dependencies
- **Zone (pure functions)**: Unit testable without HA or mocks
- **Controller**: Unit testable without HA or mocks
- **Coordinator**: Integration testable with mocked HA

### 4. Fault Isolation

Zones track their own failure state independently. One zone failing doesn't affect other zones. The controller aggregates zone statuses to determine overall health.

## Controller Mode Evaluation

The controller's `evaluate()` method dispatches to mode-specific functions:

```
evaluate(now) → ControllerActions
    └── mode dispatch (checked once)
        ├── disabled → _evaluate_disabled_mode()
        ├── all_on   → _evaluate_all_on_mode()
        ├── all_off  → _evaluate_all_off_mode()
        ├── flush    → _evaluate_flush_mode()
        ├── cycle    → _evaluate_cycle_mode(now)
        └── auto     → _evaluate_auto_mode(now)
```

Each mode function:
- Returns complete `ControllerActions` (valves + heat_request + summer_mode)
- Evaluates ALL zones at once (not per-zone)
- Is independently unit-testable
- Is a pure function (deterministic, no side effects)

### Mode Behaviors

| Mode | Valve Action | Heat Request | Summer Mode | Notes |
|------|--------------|--------------|-------------|-------|
| disabled | no actions | unchanged | unchanged | Controller inactive |
| all_on | all open | ON | winter | Boiler fires |
| all_off | all closed | OFF | summer | No heating |
| flush | all open | OFF | summer | Circulation only |
| cycle | rotate by hour | OFF | summer | One zone at a time |
| auto | quota-based | zone-based | zone-based | Normal PID control |

## Pure Utility Modules

The `core/` directory contains additional pure modules with no HA dependencies:

### PIDController (pid.py)

PID controller implementation:
- **State**: `PIDState` frozen dataclass holds error, P/I/D terms, duty cycle
- **`update()`**: Computes new state and stores internally, returns `PIDState`
- **Anti-windup**: Prevents integral term from growing unbounded
- **`set_state()`/`reset()`**: For persistence and initialization
- **Testable**: Pure math, no I/O or HA dependencies

### EMA (ema.py)

Exponential Moving Average filter:
- **Stateless function**: `calculate_ema(current, previous, alpha)`
- **Used by**: ZoneRuntime for temperature smoothing
- **Testable**: Pure math

### History (history.py)

Observation period calculations:
- **`get_observation_start()`**: Calculate 2-hour window start time
- **`calculate_period_elapsed()`**: Seconds since window start
- **Testable**: Pure datetime calculations
