# Underfloor Heating Controller

[![GitHub Release](https://img.shields.io/github/v/release/lnagel/hass-ufh-controller?style=flat-square)](https://github.com/lnagel/hass-ufh-controller/releases)
[![License](https://img.shields.io/github/license/lnagel/hass-ufh-controller?style=flat-square)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz/)
[![CI](https://img.shields.io/github/actions/workflow/status/lnagel/hass-ufh-controller/checks.yml?branch=main&style=flat-square&label=tests)](https://github.com/lnagel/hass-ufh-controller/actions)

A Home Assistant custom integration for intelligent multi-zone underfloor heating control. Uses PID-based temperature regulation with coordinated valve scheduling to keep your home comfortable while minimizing energy waste and valve wear.

## Why Use This?

Most underfloor heating systems either run valves in simple on/off mode (inefficient, causes temperature swings) or require expensive proprietary controllers. This integration gives you:

- **Precise temperature control** - PID algorithm maintains stable room temperatures without overshooting
- **Smart valve scheduling** - Coordinates multiple zones to prevent valve rapid-cycling and reduce wear
- **Energy savings** - Automatically stops heating when windows are open, captures waste heat from hot water cycles
- **Full Home Assistant integration** - Climate entities, presets, automations, and dashboards work just like any other HA device

## Features

### Intelligent Temperature Control
- **PID regulation** for each zone - no more temperature swings from simple thermostats
- **Duty cycle scheduling** - zones get proportional heating time based on demand
- **Minimum run times** - prevents short valve cycles that cause wear and inefficiency

### Energy Efficiency
- **Window/door detection** - automatically blocks heating when windows are open
- **DHW latent heat capture** - flush circuits can use waste heat from hot water heating
- **Boiler summer mode** - disables heating circuit when not needed

### Multiple Operation Modes
| Mode | Description |
|------|-------------|
| **Automatic** | Normal PID-based control with quota scheduling |
| **Flush** | All valves open for system flushing (circulation only, no firing) |
| **Cycle** | Diagnostic mode - rotates through zones on 8-hour schedule |
| **All On** | Maximum heating - all valves open |
| **All Off** | Heating disabled - all valves closed |

### Home Assistant Integration
- Native climate entities with HVAC modes and presets
- Sensors for duty cycle, PID values, and controller status
- Binary sensors for zone blocked state and heat requests
- Full UI configuration - no YAML required
- Multi-instance support - run multiple controllers for different heat sources

## Requirements

- Home Assistant 2025.10 or newer
- A hydronic (water-based) underfloor heating system with:
  - Temperature sensor for each zone
  - Controllable valve switch for each zone
  - (Optional) Boiler heat request switch or summer mode control
  - (Optional) Window/door sensors

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/lnagel/hass-ufh-controller` with category **Integration**
4. Search for "Underfloor Heating Controller" and install
5. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/lnagel/hass-ufh-controller/releases)
2. Extract and copy `custom_components/ufh_controller` to your `config/custom_components` directory
3. Restart Home Assistant

## Quick Start

### 1. Add the Integration

1. Go to **Settings → Devices & Services**
2. Click **Add Integration**
3. Search for "Underfloor Heating Controller"
4. Enter a name for your controller (e.g., "Ground Floor Heating")

### 2. Configure Boiler Connection (Optional)

You can optionally connect the controller to your boiler:

| Setting | Purpose |
|---------|---------|
| Heat Request Switch | Tells boiler when heat is needed |
| DHW Active Sensor | Enables DHW priority and flush circuit heat capture |
| Summer Mode Select | Automatically enables/disables boiler heating circuit |

### 3. Add Heating Zones

1. Go to **Settings → Devices & Services → Underfloor Heating Controller**
2. Click **Add Heating Zone**
3. Configure each zone with:
   - Name (e.g., "Living Room")
   - Temperature sensor entity
   - Valve switch entity
   - (Optional) Window sensors for that room

### 4. Set Up Presets

Each zone supports temperature presets:

| Preset | Default | Use Case |
|--------|---------|----------|
| Home | 21°C | Normal occupancy |
| Away | 16°C | Extended absence |
| Eco | 19°C | Energy saving (overnight, workday) |
| Comfort | 22°C | Extra warmth |
| Boost | 25°C | Quick warm-up |

## How It Works

### PID Temperature Control

Each zone runs an independent PID controller that calculates a **duty cycle** (0-100%) based on temperature error. A zone with 50% duty cycle should have its valve open for half of each observation period.

### Observation Periods

Time is divided into 2-hour observation periods (aligned to even hours: 00:00, 02:00, etc.). The controller ensures each zone's valve is open for its quota of time within each period, preventing rapid valve cycling while maintaining comfort.

### Heat Request Coordination

The controller aggregates zone demands and signals the boiler:
1. Waits for valve to fully open (configurable delay)
2. Checks that zone has enough quota remaining
3. Only requests heat when zones are ready to use it

This prevents short boiler cycles and improves efficiency.

## Entities Created

### Per Controller
| Entity | Description |
|--------|-------------|
| `select.*_mode` | Operation mode selector |
| `switch.*_flush_enabled` | DHW latent heat capture toggle |
| `sensor.*_requesting_zones` | Count of zones currently heating |
| `binary_sensor.*_status` | Controller health (problem when degraded) |

### Per Zone
| Entity | Description |
|--------|-------------|
| `climate.*` | Main control - temperature, mode, presets |
| `sensor.*_duty_cycle` | Current heating demand (0-100%) |
| `sensor.*_pid_error` | Temperature error (setpoint - current) |
| `binary_sensor.*_blocked` | Whether zone is blocked (window open, etc.) |
| `binary_sensor.*_heat_request` | Whether zone is contributing to heat demand |

## Configuration Options

### Timing Parameters

Access via **Settings → Devices & Services → [Controller] → Configure**:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Observation Period | 2 hours | Scheduling window for valve quotas |
| Minimum Run Time | 9 min | Shortest allowed valve run |
| Valve Open Time | 3.5 min | Delay before requesting heat |
| Closing Warning | 4 min | Stop requesting heat before quota ends |
| Window Block Time | 10 min | Cumulative open time to block heating |

### PID Tuning

Configure per zone via the zone device's **Configure** button:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Kp | 50.0 | Proportional gain - response strength |
| Ki | 0.001 | Integral gain - eliminates steady-state error |
| Kd | 0.0 | Derivative gain - damping (usually 0 for UFH) |

The defaults work well for most underfloor heating systems. Increase Kp if rooms heat too slowly; decrease if you see overshooting.

## Troubleshooting

### Zone Won't Heat

1. Check the zone's `blocked` binary sensor - if ON, a window may be open
2. Verify the valve switch entity is working
3. Check the controller mode is set to "Automatic"
4. Look at the duty cycle sensor - 0% means the room is at or above setpoint

### Temperature Oscillating

1. Reduce Kp (proportional gain) to slow the response
2. Ensure your temperature sensor isn't affected by drafts or direct sunlight
3. Check that valve open time allows the valve to fully open before heat is requested

### Controller Status Shows Problem

The controller tracks recorder query failures:
- **Degraded**: Some queries failing, using fallbacks
- **Fail-safe**: Extended failures, valves closed for safety

Check Home Assistant logs for recorder issues.

## Documentation

For detailed technical documentation, see:
- [Technical Specification](docs/specification.md) - Full system design and algorithm details
- [Contributing Guide](CONTRIBUTING.md) - Development setup and coding standards

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Based on a proven OpenHAB implementation, redesigned from the ground up for Home Assistant with native integrations, modern Python practices, and comprehensive testing.
