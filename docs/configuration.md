# Configuration Reference


This section provides detailed documentation for all configuration parameters in the Underfloor Heating Controller. Each parameter directly affects how the heating system operates.

### Timing Parameters

Timing parameters control the scheduling, valve operation, and observation windows used by the controller. All values are in seconds unless otherwise noted.

#### observation_period

**Default:** 7200 seconds (2 hours)
**Range:** 1800-14400 seconds (30 minutes to 4 hours)
**Config location:** Controller subentry → `data.timing.observation_period`

The observation period defines the time window used for quota-based valve scheduling. Each zone is allocated a "quota" of valve-on time based on its PID-calculated duty cycle, and this quota is distributed across the observation period.

Commands are re-sent at least once per period for external dead-man-switch compatibility.

**How it works:** Observation periods are aligned to midnight and use the exact configured duration. When an observation period ends, a new one begins and all zone quotas reset. The controller calculates how much time each zone's valve has been open during the current period (`used_duration`) and compares it to how much time it should be open (`requested_duration = duty_cycle% × observation_period`).

**Note:** When a period doesn't divide evenly into 24 hours, the last period of the day will be shorter (truncated at midnight). The next day starts fresh from midnight.

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

### PID Parameters

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

---

### Temperature Smoothing

#### temp_ema_time_constant (EMA Filter Time Constant)

**Default:** 600 seconds (10 minutes)
**Range:** 0-1800 seconds (0 to 30 minutes)
**Config location:** Zone subentry → `data.temp_ema_time_constant`

The time constant for the Exponential Moving Average (EMA) filter applied to temperature sensor readings. This low-pass filter smooths out sensor noise and rapid fluctuations before the temperature is used in PID calculations and displayed in the climate entity.

**How it works:** The EMA filter applies the formula: `filtered = α × raw + (1 - α) × previous_filtered`, where the smoothing factor `α = dt / (τ + dt)`. Here, `τ` is the time constant and `dt` is the time since the last reading (typically 60 seconds). Higher time constants result in more smoothing (slower response to changes), while lower values allow faster response but less noise filtering.

**Examples:**
- With `temp_ema_time_constant=600s` (10 minutes) and `dt=60s`:
  - `α = 60 / (600 + 60) = 0.091`
  - Each new reading contributes about 9% to the filtered value
  - A sudden 1°C sensor spike would only raise the filtered temperature by ~0.09°C
- With `temp_ema_time_constant=0s`: No filtering applied, raw sensor values are used directly
- With `temp_ema_time_constant=300s` (5 minutes):
  - `α = 60 / (300 + 60) = 0.167`
  - Faster response, less smoothing than the default

**Restart behavior:** The filtered temperature value is persisted across Home Assistant restarts. On startup, the EMA continues from its previous value, ensuring smooth operation without step changes or re-initialization artifacts.

**Why it matters:** Temperature sensors (especially wireless ones like Zigbee) can produce noisy readings due to measurement variance, RF interference, or environmental factors. Without filtering, this noise propagates to the PID controller, causing unnecessary valve cycling and wear. The EMA filter provides a clean, stable temperature signal while maintaining responsiveness to actual temperature changes.

**Tip:** Start with the default 600s (10 minutes). If the system feels sluggish, reduce to 300s. If you see excessive valve cycling, increase to 900s or higher.

---

### PID Parameters (continued)

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

### Setpoint Parameters

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

### Preset Temperatures

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

### Controller-Level Configuration

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
