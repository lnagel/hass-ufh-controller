# Quickstart Guide

Get your underfloor heating system up and running with this step-by-step guide.

## Prerequisites

Before installing, ensure you have:

### Hardware Requirements

- **Temperature sensor per zone** - Any Home Assistant compatible sensor (Zigbee, Z-Wave, WiFi, etc.)
- **Valve switch per zone** - A controllable switch for each zone valve (relay board, smart switch, etc.)
- **Optional: Boiler control** - Either a heat request relay or EMS-ESP for boiler communication

### Home Assistant Entities

Verify your entities are working before setup:

1. Go to **Developer Tools → States**
2. Search for your temperature sensor (e.g., `sensor.living_room_temperature`)
   - Should show a numeric temperature value
3. Search for your valve switch (e.g., `switch.zone_1_valve`)
   - Should show `on` or `off` state
   - Test toggling it to verify valve control works

### Entity Checklist

| Entity Type | Example | Purpose |
|-------------|---------|---------|
| Temperature sensor | `sensor.bedroom_temperature` | Required per zone |
| Valve switch | `switch.bedroom_valve` | Required per zone |
| Pump request switch | `switch.ufh_circulation_pump` | Optional: independent circulation pump |
| Heat request switch | `switch.boiler_heat_request` | Optional: signals boiler to fire |
| Summer mode select | `select.boiler_summer_mode` | Optional: EMS-ESP boiler control |
| DHW active sensor | `binary_sensor.boiler_dhw_active` | Optional: hot water priority |
| Supply temp sensor | `sensor.manifold_supply_temp` | Optional: heat accounting |

## Step 1: Install the Integration

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/lnagel/hass-ufh-controller` with category **Integration**
4. Search for "Underfloor Heating Controller" and install
5. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/lnagel/hass-ufh-controller/releases)
2. Extract `custom_components/ufh_controller` to your `config/custom_components` directory
3. Restart Home Assistant

After installation, the integration appears in Settings → Devices & Services → Add Integration.

## Step 2: Create the Controller

Navigate to **Settings → Devices & Services → Add Integration** and search for "Underfloor Heating Controller".

### Required Field

| Field | What to Enter |
|-------|---------------|
| **Name** | A descriptive name (e.g., "Ground Floor Heating") |

### Optional Fields - Decision Guide

**Do you have an EMS-ESP boiler?**
→ Configure `summer_mode_entity` to point to your boiler's summer mode select entity. This automatically enables/disables the heating circuit.

**Do you have a simple boiler relay?**
→ Configure `heat_request_entity` to point to your relay switch. The controller turns this on when zones need heat.

**Do you have a separate circulation pump?**
→ Configure `pump_request_entity` to point to your pump relay switch. The controller turns this on when any zone valve is fully open, enabling residual heat distribution even after the boiler stops firing.

**Boiler always on or controlled externally?**
→ Leave both blank. The controller will manage valves only.

**Do you want DHW (hot water) priority?**
→ Configure `dhw_active_entity` to point to a sensor that indicates when your boiler is heating hot water. This prevents new heating cycles during DHW and enables flush circuit heat capture.

**Do you want fair heat accounting?**
→ Configure `supply_temp_entity` to point to your manifold supply temperature sensor, and set `supply_target_temp` to your expected supply temperature (typically 35-45°C for UFH).

Click **Submit** to create the controller.

## Step 3: Add Your First Zone

After creating the controller, add a heating zone:

1. Go to **Settings → Devices & Services**
2. Find "Underfloor Heating Controller"
3. Click **"+ Add Heating Zone"**

### Required Fields

| Field | What to Enter |
|-------|---------------|
| **Name** | Zone name (e.g., "Living Room") |
| **Temperature Sensor** | Select your zone's temperature sensor |
| **Valve Switch** | Select the switch that controls this zone's valve |

### Optional Fields

| Field | When to Use | Default |
|-------|-------------|---------|
| **Circuit Type** | Set to "flush" for bathroom circuits that only capture DHW waste heat | regular |
| **Window Sensors** | Add door/window sensors to pause heating when open | none |
| **Area** | Assign to a Home Assistant area for organization | none |
| **Setpoint Min/Max** | Customize allowed temperature range | 16-28°C |
| **Setpoint Default** | Initial target temperature | 21°C |
| **PID Parameters** | Leave defaults unless you have tuning experience | kp=50, ki=0.001, kd=0 |
| **EMA Time Constant** | Increase if you see temperature oscillation | 600s (10 min) |

### Presets (Optional)

Configure preset temperatures for quick switching:

| Preset | Typical Use | Suggested Value |
|--------|-------------|-----------------|
| Home | Normal occupied comfort | 21°C |
| Away | Extended absence (vacation) | 16°C |
| Eco | Daily energy saving (night, work hours) | 19°C |
| Comfort | Extra comfort when desired | 22°C |
| Boost | Rapid heating (bathroom before shower) | 25°C |

Leave presets blank if you prefer manual setpoint control only.

Click **Submit** to create the zone.

## Step 4: Verify It's Working

### Find Your Entities

1. Go to **Settings → Devices & Services → Devices**
2. Search for your controller name
3. You should see two devices:
   - **Controller device** - Contains mode selector and status
   - **Zone device** - Contains climate entity and sensors

### Check the Controller

1. Open the controller device
2. Find `select.{controller}_mode` - should show **"Heat"**
3. Find `binary_sensor.{controller}_status` - should show **"OK"** (not "Problem")

### Check the Zone

1. Open the zone device
2. Find `climate.{controller}_{zone}` - should show current temperature
3. Find `sensor.{zone}_duty_cycle` - shows current heating demand (0-100%)

### Test Valve Control

1. Change the controller mode to **"All On"**
2. Verify the valve switch turns on (check your relay or listen for valve actuation)
3. Change back to **"Heat"** for normal operation

### Expected Initial Behavior

- **First few minutes**: Zone gathers temperature data, duty cycle may be 0%
- **After ~2 minutes**: PID controller starts calculating, duty cycle reflects heating demand
- **Valve cycling**: Valves open/close based on quota within 2-hour observation periods
- **Heat request**: If configured, boiler fires when valves are open and zones need heat

## Step 5: Basic Operation

### Adjusting Temperature

- Use the climate card to adjust the target temperature
- Or use presets for quick switching between common temperatures

### Using the Mode Selector

| Mode | When to Use |
|------|-------------|
| **Heat** | Normal operation - use this 99% of the time |
| **Flush** | Weekly pipe flushing (schedule via automation) |
| **Cycle** | Diagnostics - rotates through zones every 8 hours |
| **All On** | Testing - opens all valves, maximum heating |
| **All Off** | Summer/maintenance - closes all valves |
| **Off** | Controller inactive, no actions taken |

### Understanding Zone Status

The climate entity's `hvac_action` shows current state:

| Action | Meaning |
|--------|---------|
| **Heating** | Zone is actively receiving heat |
| **Idle** | Zone is enabled but not currently receiving heat |
| **Off** | Zone is disabled |

## Troubleshooting

### Zone Shows "Unavailable"

**Cause**: Temperature sensor not providing data.

**Fix**:
1. Check the sensor entity in Developer Tools → States
2. Ensure the sensor is online and reporting values
3. Check battery if wireless sensor

### Valve Won't Turn On

**Possible causes**:

1. **Mode not set to "Heat"** - Check the mode selector
2. **Zone disabled** - Set zone HVAC mode to "Heat" (not "Off")
3. **Quota exhausted** - Zone has used its time budget for the current 2-hour period; wait for the next period
4. **Temperature at setpoint** - No heating needed; duty cycle will be 0%

**Debug**: Check `sensor.{zone}_duty_cycle`. If >0%, the zone wants heat. If 0%, the room is at temperature.

### Temperature Oscillating

**Cause**: PID responding too aggressively to sensor noise.

**Fix**: Increase `temp_ema_time_constant` in zone settings (try 900s or 1200s).

### Status Shows "Problem"

**Cause**: One or more zones have sensor failures.

**Fix**: Check each zone's climate entity for "unavailable" status and fix the underlying sensor issue.

### Heat Request Not Firing

**Cause**: Valves not fully open yet, or quota running low.

**Fix**: Wait for `valve_open_time` (default 3.5 minutes) after a valve turns on. The controller waits for valves to fully open before requesting heat.

## Next Steps

Now that your first zone is working:

- **Add more zones** - Repeat Step 3 for each heating zone
- **Tune PID parameters** - See [Control Algorithm](control_algorithm.md) for tuning guidance
- **Configure automations** - Schedule presets, integrate with presence detection
- **Set up Tasmota relays** - See [Tasmota Configuration](tasmota.md) for relay board setup
- **Understand heat accounting** - See [Heat Accounting](heat_accounting.md) for supply temperature weighting
- **Review all parameters** - See [Configuration Reference](configuration.md) for detailed parameter documentation
