# Plan: Switch from PID to I-PD Control Logic

## Background

**PID** (Proportional-Integral-Derivative): All three terms act on the error signal (`setpoint - measurement`). When the setpoint changes, the proportional term causes an immediate jump in output ("proportional kick"), which can cause overshoot in slow thermal systems like underfloor heating.

**I-PD** (Integral - Proportional-Derivative on measurement): Only the integral term acts on the error. P and D act on the measurement (process variable) directly. This eliminates proportional and derivative kick on setpoint changes, giving smoother control that is better suited to hydronic heating with long thermal time constants.

### I-PD Formula

```
error       = setpoint - current
P           = -Kp × current                              (acts on measurement)
I           = clamp(prev_I + Ki × error × dt, min, max)  (acts on error, same as PID)
D           = -Kd × (current - last_measurement) / dt    (acts on measurement rate)
duty_cycle  = clamp(P + I + D, 0, 100)
```

### Bumpless Initialization

On the very first update (no prior state), the integral is initialized to `Kp × current` so that `P + I = 0` at startup. This prevents a prolonged zero-output period while the integral "charges up" to compensate for the P term. Without this, a room at 20°C with Kp=50 would have P=-1000 and the integral would need hundreds of updates to produce any heating output.

## Changes

### 1. `custom_components/ufh_controller/core/pid.py` — Core algorithm

- **`PIDState`**: Add `measurement: float | None = None` field (with default for backward compatibility). This stores the last process variable reading for the D term.
- **`PIDController.update()`**: Rewrite to implement I-PD:
  - P = `-self.kp * current`
  - I = `prev_integral + self.ki * error * dt` with bumpless init: when `self._state is None`, use `self.kp * current` as `prev_integral` instead of `0.0`
  - D = `-self.kd * (current - last_measurement) / dt` where `last_measurement` comes from `self._state.measurement`; on first update, use `current` (no derivative kick)
- **Docstrings**: Update class/method docstrings from "PID" to "I-PD", document the bumpless initialization behavior.

### 2. `custom_components/ufh_controller/const.py` — Default parameters

Update `DEFAULT_PID` to match I-PD operating characteristics:

| Parameter      | Old (PID) | New (I-PD) | Rationale |
|----------------|-----------|------------|-----------|
| `kp`           | 50.0      | 50.0       | No change; provides proportional damping based on measurement |
| `ki`           | 0.001     | 0.1        | Must be larger — integral is now solely responsible for setpoint tracking |
| `kd`           | 0.0       | 0.0        | No change; derivative still disabled by default for slow hydronic systems |
| `integral_min` | 0.0       | 0.0        | No change |
| `integral_max` | 100.0     | 1500.0     | Must accommodate `duty_cycle + Kp × measurement` at steady state (e.g., 50% + 50×21 = 1100) |

### 3. `custom_components/ufh_controller/coordinator.py` — State persistence

- **`_build_coordinator_data()`** (~line 1147): Add `"pid_measurement": pid_state.measurement if pid_state else None` to stored zone data.
- **`_restore_zone_state()`** (~line 451): Add `measurement=zone_state.get("pid_measurement")` to the `PIDState()` constructor for state restoration.

### 4. `custom_components/ufh_controller/core/zone.py` — Docstring updates

- Update `update_pid()` docstring to reference "I-PD" instead of "PID".
- No structural code changes — the call signature is identical.

### 5. `custom_components/ufh_controller/sensor.py` — Semantic note

The `pid_proportional` sensor will now display `-Kp × current` (a large negative number at typical temperatures) instead of `Kp × error`. The unit (%) and entity structure remain the same. No code changes needed in this file — the data plumbing already passes through whatever `PIDState.proportional` contains.

### 6. `tests/unit/test_pid.py` — Test rewrite

All existing PID tests must be updated to reflect I-PD behavior:

- **Proportional tests**: Expected values change from `kp * error` to `-kp * current`
- **Derivative tests**: Expected values change from `kd * d(error)/dt` to `-kd * d(measurement)/dt`
- **Combined tests**: All expected output values recalculated
- **New tests**:
  - Bumpless initialization (first update integral = `kp * current`)
  - D term uses measurement derivative, not error derivative
  - Setpoint change does not cause proportional kick
  - State restoration with `measurement` field

### 7. `docs/control_algorithm.md` — Documentation

- Rename "PID Controller" section to "I-PD Controller"
- Update formula descriptions
- Add explanation of why I-PD is used (no proportional/derivative kick)
- Document bumpless initialization
- Update the "PID Integration Pausing" section heading and references

### 8. Other references — Bulk rename

Search and update "PID" references in docstrings and comments across:
- `core/zone.py` — docstrings mentioning PID
- `coordinator.py` — comments mentioning PID
- `sensor.py` — if any comments reference PID behavior
- `CLAUDE.md` — Domain Knowledge section mentions PID

Translation keys (`pid_proportional`, `pid_integral`, etc.) and config entry keys stay as-is to avoid breaking entity IDs and stored state.

## Safety Considerations

1. **Bumpless initialization** prevents the cold-start problem where no heating occurs for an extended period.
2. **State restoration** preserves integral accumulator and last measurement across restarts.
3. **Default `ki` increase** (0.001 → 0.1) ensures the integral responds fast enough for setpoint tracking. With a 1°C error, the integral changes by 6% per minute, reaching operating point within minutes rather than days.
4. **Default `integral_max` increase** (100 → 1500) is necessary because the integral at steady state must compensate for `-Kp × measurement` (e.g., -1050 at 21°C).

## Breaking Changes

- **Tuning parameters**: Existing user configurations with custom PID gains will behave differently. Users who have tuned `kp`, `ki`, or `integral_max` will need to re-tune for I-PD behavior.
- **Sensor values**: The `pid_proportional` sensor will show large negative values (e.g., -1050 at 21°C with kp=50) instead of small values around 0 at steady state. The `pid_integral` sensor will show large positive values at steady state.
- **Stored state**: On first restart after upgrade, the stored `integral` value from PID will be used by I-PD, which expects a much larger value. The controller will re-converge within minutes due to the higher default ki.
