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
│  (ZoneRuntime)                                                          │
│                                                                         │
│  Responsibility: Single Zone Control                                    │
│                                                                         │
│  - Own its config, state, and PID controller                            │
│  - update_temperature(raw_temp, dt) - apply EMA smoothing               │
│  - update_pid(dt, mode) - update PID controller                         │
│  - update_historical(period_avg, open_avg, window_open, elapsed)        │
│  - update_failure_state(now, temp_unavailable, recorder_failure)        │
│  - evaluate(controller_state, timing) → ZoneAction                      │
│  - should_request_heat(timing) → bool                                   │
│  - Properties: setpoint, enabled (with validation/clamping)             │
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

Zone updates happen in distinct stages, each with a clear purpose:

| Stage | Method | Purpose |
|-------|--------|---------|
| 1. Temperature | `update_temperature()` | Apply EMA smoothing to raw sensor reading |
| 2. PID | `update_pid()` | Calculate duty cycle (paused when blocked) |
| 3. Historical | `update_historical()` | Update averages and calculate quota usage |
| 4. Failure | `update_failure_state()` | Track zone health status |
| 5. Evaluate | `evaluate()` | Determine valve action |

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

### Zone (ZoneRuntime)

The zone manages **single-zone** state and decisions:

- **State Ownership**: Temperature, setpoint, valve state, PID state
- **Temperature Processing**: EMA smoothing
- **PID Control**: Update PID controller, handle pause conditions
- **Historical Tracking**: Used duration, requested duration
- **Failure Isolation**: Track zone-specific failures independently
- **Evaluation**: Determine valve action based on quota and state

Zones are **self-contained**. They receive inputs and produce outputs without knowing about other zones or Home Assistant.

## Design Principles

### 1. Single Responsibility

Each layer has one job:
- Coordinator: HA integration
- Controller: Multi-zone orchestration
- Zone: Single-zone control

### 2. Dependency Direction

Dependencies flow downward:
- Coordinator depends on Controller
- Controller depends on Zone
- Zone depends on nothing (pure logic)

### 3. Testability

- **Zone**: Unit testable without HA or mocks
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
