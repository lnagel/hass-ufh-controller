# Architecture

This document describes the layered architecture of the UFH Controller and the responsibilities of each component.

## Layer Overview

**Coordinator** (Home Assistant integration layer)
- Reads HA entity states, queries Recorder, executes service calls, manages storage
- Passes data to Controller, executes returned actions

**Controller** (Pure decision engine)
- Holds global config/state (status, mode, timing, DHW, flush)
- `evaluate()` returns all actions (valves, heat_request, flush_request) with no side effects

**Zone** (Single-zone control)
- Owns config, PID controller, and mutable state
- Pure function `evaluate_zone()` for valve decisions

## Data Flow

Each coordinator update cycle follows this flow:

```
Coordinator._async_update_data()
    │
    ├─► Update observation period (observation_start, period_elapsed)
    │
    ├─► Update DHW state from HA entity
    │
    ├─► For each zone:
    │       ├─► Read raw temperature from HA
    │       ├─► zone.update_temperature(raw_temp, dt)
    │       ├─► zone.update_pid(dt, mode)
    │       ├─► Query Recorder for valve position and window state
    │       ├─► zone.update_historical(valve_position, window)
    │       ├─► zone.update_supply_coefficient(supply_temp, supply_target_temp)
    │       ├─► zone.update_heat_state()
    │       ├─► zone.update_used_duration(dt)
    │       ├─► Sync valve state from HA entity
    │       └─► zone.update_failure_state(now, temp_unavail, valve_unavail)
    │
    ├─► controller.evaluate(now) → ControllerActions
    │       ├─► Evaluate regular zones first
    │       ├─► Compute flush_request
    │       ├─► Evaluate flush zones
    │       ├─► Aggregate heat_request from flowing zones
    │       └─► Return actions (valves, heat_request, flush_request)
    │
    ├─► Execute returned actions:
    │       ├─► Store heat_request in controller state
    │       ├─► Valve actions via switch services
    │       ├─► Heat request via switch service (if present)
    │       └─► Summer mode via select service (if present)
    │
    └─► Save state to storage
```

## Design Principles

### 1. Single Responsibility

Each layer has one job:
- Coordinator: HA integration
- Controller: Multi-zone orchestration
- Zone: Single-zone control

### 2. Dependency Direction

Dependencies flow downward:
- Coordinator depends on Controller, Zone, HeatingCurve, Recorder (HA-specific)
- Controller depends on Zone (ZoneRuntime + pure functions), HeatingCurve
- Zone depends on PID, EMA (pure utilities)
- PID, EMA, History, HeatingCurve depend on nothing (stdlib only)

### 3. Testability

- **PID, EMA, History, HeatingCurve**: Unit testable, no dependencies
- **Zone (pure functions)**: Unit testable without HA or mocks
- **Controller**: Unit testable without HA or mocks
- **Coordinator**: Integration testable with mocked HA

### 4. Fault Isolation

Zones track their own failure state independently. One zone failing doesn't affect other zones. The controller aggregates zone statuses to determine overall health.
