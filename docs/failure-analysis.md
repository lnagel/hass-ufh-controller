# Failure Analysis - UFH Controller

This document analyzes potential failure scenarios in the UFH Controller integration and evaluates whether the current implementation handles them safely.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Hardware Failure Scenarios](#2-hardware-failure-scenarios)
3. [Software & Home Assistant Failures](#3-software--home-assistant-failures)
4. [Control Algorithm Issues](#4-control-algorithm-issues)
5. [Configuration & Data Issues](#5-configuration--data-issues)
6. [Environmental & External Factors](#6-environmental--external-factors)
7. [Safety-Critical Scenarios](#7-safety-critical-scenarios)
8. [Recommendations](#8-recommendations)

---

## 1. Executive Summary

### Overall Assessment

The current implementation provides **reasonable fail-safe behavior** for most common scenarios but has several areas where safety could be improved. The system generally fails toward a **safe-off state** but lacks explicit safeguards against some edge cases.

### Key Findings

| Category | Safe | Partially Safe | Unsafe |
|----------|------|----------------|--------|
| Hardware Failures | 2 | 4 | 1 |
| Software Failures | 3 | 2 | 0 |
| Algorithm Issues | 2 | 3 | 1 |
| Configuration Issues | 1 | 2 | 0 |
| Environmental Factors | 2 | 2 | 0 |
| Safety Critical | 1 | 3 | 1 |

**Legend:**
- **Safe**: Implementation handles failure gracefully
- **Partially Safe**: Some handling exists but improvements needed
- **Unsafe**: No handling, could lead to problems

---

## 2. Hardware Failure Scenarios

### 2.1 Temperature Sensor Failure

#### Scenario: Sensor Returns Invalid Values (NaN, "unknown", "unavailable")

**Current Implementation:**
```python
# coordinator.py:287-296
current_temp: float | None = None
if temp_state is not None:
    try:
        current_temp = float(temp_state.state)
    except (ValueError, TypeError):
        LOGGER.warning(
            "Invalid temperature state for %s: %s",
            runtime.config.temp_sensor,
            temp_state.state,
        )
```

```python
# controller.py:204-206
if current_temp is None:
    # No temperature reading - maintain last duty cycle
    return runtime.state.duty_cycle
```

**Assessment: PARTIALLY SAFE** ⚠️

- Invalid states are caught and logged
- Last duty cycle is maintained when temperature unavailable
- **Issue**: Maintaining last duty cycle indefinitely could lead to over/under heating if sensor remains unavailable for extended periods
- **Missing**: No timeout mechanism to eventually disable heating if sensor stays unavailable

---

#### Scenario: Sensor Reports Wildly Incorrect Values (e.g., -40°C or 100°C)

**Current Implementation:** No explicit validation of temperature range.

**Assessment: UNSAFE** ❌

- A sensor reporting -40°C would cause PID to demand 100% duty cycle continuously
- A sensor reporting 100°C would cause 0% duty cycle (heating off)
- **Missing**: Temperature sanity bounds check (e.g., 0°C to 50°C reasonable range)

---

#### Scenario: Sensor Becomes Stuck at One Value

**Current Implementation:** No change detection or staleness check.

**Assessment: PARTIALLY SAFE** ⚠️

- PID will eventually reach steady state based on stuck value
- If stuck value is near setpoint, system will stabilize
- If stuck value is far from setpoint, continuous heating/cooling
- **Missing**: Staleness detection (no change over extended period triggers warning)

---

### 2.2 Valve Actuator Failure

#### Scenario: Valve Stuck Open (Actuator Fails Open)

**Current Implementation:** No physical valve position feedback.

**Assessment: PARTIALLY SAFE** ⚠️

- System assumes valve follows commands
- Stuck-open valve would heat zone continuously when boiler active
- **Mitigation**: Heat request aggregation means boiler only fires when zones actively request
- **Missing**: No detection mechanism for valve state mismatch

---

#### Scenario: Valve Stuck Closed (Actuator Fails Closed)

**Current Implementation:** No physical valve position feedback.

**Assessment: PARTIALLY SAFE** ⚠️

- Zone would never receive heat
- PID integral would wind up, but bounded by `integral_max`
- User would notice room stays cold
- **Missing**: Alarm or notification when valve commanded open but room temperature doesn't respond

---

#### Scenario: Valve Actuator Responds Slowly

**Current Implementation:**
```python
# zone.py:15
_VALVE_OPEN_THRESHOLD = 0.85

# zone.py:214-215
if zone.open_state_avg < _VALVE_OPEN_THRESHOLD:
    return False
```

**Assessment: SAFE** ✅

- `valve_open_time` parameter (default 3.5 minutes) accounts for slow valve response
- Heat request waits until valve has been commanded open for sufficient time
- Configurable via options flow

---

### 2.3 Network/Communication Failures

#### Scenario: Wi-Fi/Zigbee/Z-Wave Temporarily Loses Connection to Valve

**Current Implementation:** Relies on Home Assistant entity states.

**Assessment: PARTIALLY SAFE** ⚠️

- HA typically shows entities as "unavailable" when communication lost
- Service calls to unavailable switches will fail silently
- Valve remains in last physical state
- **Missing**: Explicit handling of "unavailable" entity state for valves

---

#### Scenario: Network Loss During Heat Request

**Current Implementation:**
```python
# coordinator.py:391-413
async def _call_switch_service(self, entity_id: str, *, turn_on: bool) -> None:
    service = "turn_on" if turn_on else "turn_off"
    if not self.hass.services.has_service("switch", service):
        LOGGER.debug(...)
        return
    await self.hass.services.async_call(...)
```

**Assessment: SAFE** ✅

- Service availability is checked before calling
- Failed service calls don't crash the integration
- State will be re-evaluated on next cycle (60 seconds)

---

### 2.4 Boiler Failure

#### Scenario: Boiler Doesn't Respond to Heat Request

**Current Implementation:** No boiler acknowledgment or feedback loop.

**Assessment: N/A (External System)**

- UFH Controller cannot detect boiler failure
- User responsibility to monitor boiler health
- **Suggestion**: Document that external boiler monitoring is recommended

---

## 3. Software & Home Assistant Failures

### 3.1 Home Assistant Restart

#### Scenario: HA Restarts While Heating Active

**Current Implementation:**
```python
# coordinator.py:143-164
async def async_load_stored_state(self) -> None:
    stored_data = await self._store.async_load()
    if stored_data is None:
        self._state_restored = True
        return

    # Restore controller mode
    if "controller_mode" in stored_data:
        stored_mode = stored_data["controller_mode"]
        if stored_mode in [mode.value for mode in OperationMode]:
            self._controller.mode = stored_mode

    # Restore zone state
    zones_data = stored_data.get("zones", {})
    for zone_id, zone_state in zones_data.items():
        self._restore_zone_state(zone_id, zone_state)
```

**Assessment: SAFE** ✅

- State is persisted to Store API on every update cycle
- Controller mode, PID integral, setpoints, and enabled state are restored
- Observation period recalculates from current time (spec requirement)

---

#### Scenario: HA Crashes Without Saving State

**Current Implementation:**
```python
# coordinator.py:260-261 (in _async_update_data)
# Save state after every update for crash resilience
await self.async_save_state()
```

**Assessment: SAFE** ✅

- State saved every 60 seconds (each coordinator update cycle)
- Maximum data loss: 60 seconds of state changes
- PID integral will be restored from last save

---

### 3.2 Integration Reload

#### Scenario: User Reloads Integration

**Current Implementation:**
```python
# __init__.py:85-96
async def async_unload_entry(hass, entry) -> bool:
    LOGGER.debug("Unloading UFH Controller entry: %s", entry.entry_id)

    # Save state before unloading
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_save_state()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

**Assessment: SAFE** ✅

- Explicit state save on unload
- Reload listener registered for configuration changes
- State fully restored on reload

---

### 3.3 Recorder Database Issues

#### Scenario: Recorder Database Unavailable or Corrupted

**Current Implementation:**
```python
# history.py:135-141
entity_states = states.get(entity_id)
if not entity_states:
    # No state changes - check current state
    current_state = hass.states.get(entity_id)
    if current_state and current_state.state == on_value:
        return 1.0
    return 0.0
```

**Assessment: PARTIALLY SAFE** ⚠️

- Falls back to current state if no history
- Returns 0.0 for averages if history unavailable
- **Issue**: 0.0 window_open_avg means heating proceeds even if window check failed
- **Issue**: 0.0 valve_state_avg could reset quota calculations incorrectly

---

#### Scenario: Recorder Query Timeout

**Current Implementation:** Uses executor job but no explicit timeout.

**Assessment: PARTIALLY SAFE** ⚠️

- Recorder queries run in executor (non-blocking)
- DataUpdateCoordinator has default timeout
- **Missing**: Explicit timeout handling with graceful degradation

---

### 3.4 Service Call Failures

#### Scenario: Switch Service Call Fails

**Current Implementation:** Errors not explicitly caught.

**Assessment: SAFE** ✅

- Home Assistant service calls are async and don't block
- Coordinator update continues even if individual call fails
- State re-evaluated next cycle

---

## 4. Control Algorithm Issues

### 4.1 PID Controller Problems

#### Scenario: PID Integral Windup During Extended Window Block

**Current Implementation:**
```python
# controller.py:204-206
if current_temp is None:
    # No temperature reading - maintain last duty cycle
    return runtime.state.duty_cycle
```

```python
# pid.py:71-74
self._state.integral += error * dt
self._state.integral = max(
    self.integral_min, min(self.integral_max, self._state.integral)
)
```

**Assessment: PARTIALLY SAFE** ⚠️

- Integral is bounded by `integral_min` and `integral_max`
- However, PID continues updating even when zone is window-blocked
- When window closes, accumulated integral could cause overshoot
- **Missing**: Freeze PID integral accumulation when zone is blocked

---

#### Scenario: PID Oscillation with Bad Parameters

**Current Implementation:** User-configurable PID parameters without validation.

**Assessment: PARTIALLY SAFE** ⚠️

- Bad parameters could cause oscillation or instability
- Min run time (540s) provides some damping
- **Missing**: PID parameter sanity checks (warn if Kp too high, Ki too low)
- **Missing**: Oscillation detection

---

#### Scenario: Derivative Kick on Setpoint Change

**Current Implementation:**
```python
# pid.py:78-79
d_term = self.kd * (error - self._state.last_error) / dt
self._state.last_error = error
```

**Assessment: SAFE** ✅

- Default Kd = 0.0, so derivative term disabled by default
- With Kd > 0, derivative calculated on error (not PV), which could cause kick
- However, duty cycle clamped 0-100%, limiting impact

---

### 4.2 Time/Clock Issues

#### Scenario: System Clock Jumps Forward (DST Change, NTP Sync)

**Current Implementation:**
```python
# coordinator.py:224-228
now = datetime.now(UTC)
dt = CONTROLLER_LOOP_INTERVAL
if self._last_update is not None:
    dt = (now - self._last_update).total_seconds()
self._last_update = now
```

**Assessment: PARTIALLY SAFE** ⚠️

- Uses UTC time (DST-immune for calculations)
- `dt` calculation could be very large after clock jump
- Large `dt` could cause massive integral accumulation in single step
- **Missing**: Cap on maximum `dt` value (e.g., 2x normal interval)

---

#### Scenario: System Clock Jumps Backward

**Current Implementation:** Same as above.

**Assessment: UNSAFE** ❌

- Negative `dt` would be calculated
- PID update with dt <= 0 returns 0.0, losing current duty cycle
- Observation period calculations could become invalid
- **Missing**: Guard against negative or zero dt

---

#### Scenario: Observation Period Boundary

**Current Implementation:**
```python
# history.py:35-41
def get_observation_start(now: datetime, observation_period: int = 7200) -> datetime:
    period_hours = observation_period // 3600
    if period_hours <= 0:
        period_hours = 2
    hour = now.hour
    period_hour = hour - (hour % period_hours)
    return now.replace(hour=period_hour, minute=0, second=0, microsecond=0)
```

**Assessment: SAFE** ✅

- Properly aligns to period boundaries
- Used_duration recalculates from history each cycle
- No state carryover issues at boundary

---

### 4.3 Race Conditions

#### Scenario: User Changes Setpoint During Update Cycle

**Current Implementation:**
```python
# coordinator.py:445-449
def set_zone_setpoint(self, zone_id: str, setpoint: float) -> None:
    if self._controller.set_zone_setpoint(zone_id, setpoint):
        self.async_set_updated_data(self._build_state_dict())
        self.hass.async_create_task(self.async_save_state())
```

**Assessment: SAFE** ✅

- Home Assistant event loop is single-threaded
- State updates atomic within single event loop iteration
- Coordinator update and user action can't interleave

---

## 5. Configuration & Data Issues

### 5.1 Invalid Entity References

#### Scenario: Configured Temperature Sensor Entity Deleted

**Current Implementation:**
```python
# coordinator.py:286-296
temp_state = self.hass.states.get(runtime.config.temp_sensor)
current_temp: float | None = None
if temp_state is not None:
    try:
        current_temp = float(temp_state.state)
    except (ValueError, TypeError):
        ...
```

**Assessment: SAFE** ✅

- Gracefully handles missing entity (returns None)
- Zone continues with last duty cycle
- Logged as warning

---

#### Scenario: Configured Valve Switch Entity Deleted

**Current Implementation:** Similar pattern for valve entity.

**Assessment: PARTIALLY SAFE** ⚠️

- Service call to non-existent entity fails silently
- Zone decisions still made but can't execute
- **Missing**: Periodic validation that configured entities exist

---

### 5.2 Data Corruption

#### Scenario: Stored State File Corrupted

**Current Implementation:**
```python
# coordinator.py:148-151
stored_data = await self._store.async_load()
if stored_data is None:
    self._state_restored = True
    return
```

**Assessment: SAFE** ✅

- HA Store API handles JSON parsing
- Returns None if file corrupted
- Falls back to default state

---

#### Scenario: Zone Subentry Data Missing Required Fields

**Current Implementation:**
```python
# coordinator.py:107-108
zones.append(
    ZoneConfig(
        zone_id=zone_data["id"],  # KeyError if missing
        ...
    )
)
```

**Assessment: PARTIALLY SAFE** ⚠️

- Would raise KeyError on missing required field
- Integration would fail to load
- **Missing**: Defensive data validation with clear error messages

---

## 6. Environmental & External Factors

### 6.1 Window/Door Sensor Issues

#### Scenario: Window Sensor Battery Dies (Shows "unknown" or "unavailable")

**Current Implementation:**
```python
# history.py:255-264
async def get_window_open_average(...) -> float:
    if not window_sensors:
        return 0.0

    max_open = 0.0
    for sensor_id in window_sensors:
        avg = await get_state_average(hass, sensor_id, start, end, on_value="on")
        max_open = max(max_open, avg)

    return max_open
```

**Assessment: PARTIALLY SAFE** ⚠️

- "unavailable" state is not "on", so treated as closed
- Dead sensor allows heating to continue (fail-open for heating)
- **Trade-off**: Better than blocking heating, but wastes energy if window actually open
- **Missing**: Warning when window sensor unavailable

---

#### Scenario: Window Sensor Stuck "On" (Reports Window Always Open)

**Current Implementation:**
```python
# zone.py:163-164
if zone.window_open_avg > timing.window_block_threshold:
    return ZoneAction.TURN_OFF if zone.valve_on else ZoneAction.STAY_OFF
```

**Assessment: SAFE** ✅

- Zone blocks correctly
- User would notice room stays cold
- Can disable zone or remove sensor from config

---

### 6.2 DHW Sensor Issues

#### Scenario: DHW Active Sensor Unavailable

**Current Implementation:**
```python
# coordinator.py:265-272
async def _update_dhw_state(self) -> None:
    dhw_entity = self._controller.config.dhw_active_entity
    if dhw_entity is None:
        return

    state = self.hass.states.get(dhw_entity)
    self._controller.state.dhw_active = state is not None and state.state == "on"
```

**Assessment: SAFE** ✅

- None or unavailable state treated as "off"
- Regular circuits proceed normally
- Flush circuits don't get DHW priority (acceptable degradation)

---

### 6.3 Extreme Conditions

#### Scenario: Very Rapid Temperature Drop (Heating System Failure in Winter)

**Current Implementation:** No frost protection mode.

**Assessment: PARTIALLY SAFE** ⚠️

- PID will demand 100% duty cycle
- Valves will open, heat requested
- If boiler fails, zones stay open requesting heat
- **Missing**: Frost protection override mode
- **Missing**: Low temperature alarm

---

## 7. Safety-Critical Scenarios

### 7.1 Overheating Risk

#### Scenario: PID Malfunction Causes Continuous 100% Demand

**Current Implementation:**
```python
# pid.py:82-83
output = p_term + i_term + d_term
return max(0.0, min(100.0, output))
```

**Assessment: PARTIALLY SAFE** ⚠️

- Duty cycle clamped to 100% maximum
- Observation period limits actual valve-on time
- **But**: If all zones at 100%, continuous heating occurs
- **Missing**: Maximum temperature safety cutoff
- **Missing**: Runaway heating detection

---

### 7.2 Freezing Risk

#### Scenario: All Heating Disabled/Blocked in Winter

**Current Implementation:** No frost protection.

**Assessment: PARTIALLY SAFE** ⚠️

- "all_off" mode forces all valves closed
- "disabled" mode maintains last state
- Window blocking can disable zones
- **Missing**: Minimum temperature threshold to override blocks
- **Missing**: Frost protection mode that ignores window sensors

---

### 7.3 Valve State Inconsistency

#### Scenario: Controller State Diverges from Physical Valve State

**Current Implementation:** Fire-and-forget valve commands.

**Assessment: PARTIALLY SAFE** ⚠️

- No valve state verification
- Relies on re-sending commands each cycle
- `STAY_ON` doesn't re-send command (could drift)
- **Suggestion**: Periodically re-send valve commands to ensure sync

---

### 7.4 Complete System Failure

#### Scenario: Integration Crashes Completely

**Current Implementation:**
```python
# coordinator.py:260-261
await self.async_save_state()
```

**Assessment: SAFE** ✅

- Physical valves maintain last state
- Heat request switch maintains last state
- User can manually control via original entities
- Integration restart restores from saved state

---

### 7.5 Simultaneous Multiple Failures

#### Scenario: Multiple Sensors Fail + HA Restarts

**Current Implementation:** Each failure handled independently.

**Assessment: UNSAFE** ❌

- Cascading failures not explicitly considered
- Multiple unavailable sensors could lead to unexpected behavior
- **Missing**: System health check that halts operation if too many failures

---

## 8. Recommendations

### High Priority (Safety-Critical)

1. **Add temperature sanity bounds check**
   - Reject readings outside 0°C to 50°C
   - Log warning and use last valid reading
   - Implementation: `coordinator.py:_update_zone()`

2. **Guard against clock jumps**
   - Cap `dt` to maximum 2x normal interval (120 seconds)
   - Discard negative `dt` values
   - Implementation: `coordinator.py:_async_update_data()`

3. **Add frost protection mode**
   - Override window blocking if temperature drops below threshold (e.g., 5°C)
   - Always enable heating if any zone below frost threshold
   - Implementation: `zone.py:evaluate_zone()`

4. **Freeze PID integral during blocks**
   - Don't accumulate error when zone is window-blocked or disabled
   - Prevents overshoot when block removed
   - Implementation: `controller.py:update_zone_pid()`

### Medium Priority (Reliability)

5. **Add sensor unavailability timeout**
   - After N minutes of sensor unavailable, force zone to safe state
   - Log persistent warning
   - Implementation: New state tracking in ZoneState

6. **Validate valve entity responsiveness**
   - Periodically verify valve entities exist and respond
   - Warn user if entities become unavailable
   - Implementation: Periodic health check in coordinator

7. **Add system health metric**
   - Count unavailable sensors/actuators
   - Reduce operation or warn if health below threshold
   - Implementation: New health monitoring class

8. **Validate temperature response to heating**
   - If valve open for extended period with no temperature rise, warn user
   - Helps detect stuck valves or disconnected rooms
   - Implementation: New diagnostic feature

### Low Priority (Enhancement)

9. **Add PID parameter validation**
   - Warn if parameters outside reasonable ranges
   - Detect potential oscillation from configuration
   - Implementation: `config_flow.py` validation

10. **Add runaway heating detection**
    - Alert if room significantly overshoots setpoint
    - Could indicate stuck valve or sensor issue
    - Implementation: Diagnostic sensor

11. **Periodic valve command re-send**
    - Re-send valve commands every N cycles even for STAY_ON
    - Ensures physical state matches expected state
    - Implementation: `coordinator.py:_execute_valve_actions()`

---

## Appendix: Test Coverage for Failure Scenarios

| Scenario | Test Coverage |
|----------|---------------|
| Temperature sensor invalid | ❌ Not tested |
| Temperature sensor unavailable | ❌ Not tested |
| Valve entity missing | ❌ Not tested |
| Window sensor unavailable | ❌ Not tested |
| DHW sensor unavailable | ❌ Not tested |
| HA restart (state persistence) | ✅ `test_coordinator_persistence.py` |
| Recorder unavailable | ❌ Not tested |
| Clock jump | ❌ Not tested |
| Zone disabled | ✅ `test_zone.py` |
| Window blocking | ✅ `test_zone.py` |
| Quota scheduling | ✅ `test_zone.py` |
| DHW blocking | ✅ `test_zone.py` |
| Heat request aggregation | ✅ `test_zone.py` |
| PID anti-windup | ✅ `test_pid.py` |
| PID output clamping | ✅ `test_pid.py` |

---

*Document generated: 2026-01-06*
*Based on implementation commit: f034566*
