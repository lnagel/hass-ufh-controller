# Architecture

This document describes the layered architecture of the UFH Controller and the responsibilities of each component.

## Layer Overview

**Coordinator** (Home Assistant integration layer)
- Reads HA entity states, queries Recorder, executes service calls, manages storage
- Passes data to Controller, executes returned actions

**Controller** (Pure decision engine)
- Holds global config/state (mode, timing, DHW, flush)
- `evaluate()` returns all actions (valves, heat_request) with no side effects

**Zone** (Single-zone control)
- Owns config, PID controller, and mutable state
- Pure functions `evaluate_zone()` and `should_request_heat()` for decisions

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
    │       ├─► Query Recorder for historical averages
    │       ├─► zone.update_historical(period_avg, open_avg, ...)
    │       ├─► Sync valve state from HA entity
    │       └─► zone.update_failure_state(now, temp_unavail, recorder_fail)
    │
    ├─► controller.evaluate(now) → ControllerAction
    │       ├─► Evaluate regular zones first
    │       ├─► Compute flush_request
    │       ├─► Evaluate flush zones
    │       ├─► Compute per-zone heat_requests (dict[str, bool])
    │       └─► Return actions (valves, heat_requests, flush_request)
    │
    ├─► Execute returned actions:
    │       ├─► Store heat_requests in controller state
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
