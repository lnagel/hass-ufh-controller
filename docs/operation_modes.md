# Operation Modes


### Heat Mode (`heat`)

Default mode. Full PID control with quota-based scheduling.

- PID controllers update every 60 seconds
- Valves managed based on duty cycle and observation period quota
- Pump request: flow-gated (on when any zone has confirmed flow)
- Heat request: flow-gated and gated on pump request
- Window blocking active
- DHW priority active (if configured)
- Post-DHW residual heat capture active (if configured)
- Boiler summer_mode follows heat request, or "auto" when any zone is in fail-safe
  (see [Fault Isolation](fault_isolation.md#summer-mode-safety))

### Flush Mode (`flush`)

System maintenance mode for pipe flushing.

- All valves forced OPEN
- Pump request ON (circulation is the mode's purpose)
- Heat request OFF
- Boiler summer_mode set to "summer" (circulation only, no firing)
- Typically scheduled weekly (e.g., Saturday 02:00-02:30)

### Cycle Mode (`cycle`)

Diagnostic mode that rotates through zones.

- One zone open at a time on 8-hour rotation
- Hour 0: all closed (rest)
- Hours 1-7: zones open sequentially
- Pump request: flow-gated (on when the active zone has confirmed flow)
- Heat request OFF
- Boiler summer_mode set to "summer" (rotation only, no firing)

### All On Mode (`all_on`)

Manual override - maximum heating.

- All valves forced OPEN
- Pump request ON
- Heat request ON
- Boiler summer_mode set to "winter"

### All Off Mode (`all_off`)

Manual override - heating disabled.

- All valves forced CLOSED
- Pump request OFF
- Heat request OFF
- Boiler summer_mode set to "summer"

### Off Mode (`off`)

Controller inactive. No actions taken, entities remain in last state. This holds
even if zones enter fail-safe, which is still tracked and reported.

---

Except in `heat` mode, the summer_mode values above are enforced even when zones
enter fail-safe. See [Fault Isolation](fault_isolation.md#summer-mode-safety).

---
