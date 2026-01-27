# Underfloor Heating Controller

[![GitHub Release](https://img.shields.io/github/v/release/lnagel/hass-ufh-controller?style=flat-square)](https://github.com/lnagel/hass-ufh-controller/releases)
[![License](https://img.shields.io/github/license/lnagel/hass-ufh-controller?style=flat-square)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz/)
[![CI](https://img.shields.io/github/actions/workflow/status/lnagel/hass-ufh-controller/checks.yml?branch=main&style=flat-square&label=tests)](https://github.com/lnagel/hass-ufh-controller/actions)
[![codecov](https://codecov.io/gh/lnagel/hass-ufh-controller/branch/main/graph/badge.svg)](https://codecov.io/gh/lnagel/hass-ufh-controller)

**The only Home Assistant integration designed specifically for hydronic underfloor heating systems.**

While other thermostats adapt radiator or TRV logic to UFH, this integration is built from the ground up to handle UFH's unique characteristics: high thermal mass, slow response times, and the need to coordinate multiple zones sharing a single heat source.

## Why This Exists

The Home Assistant thermostat ecosystem has excellent options for TRVs ([Better Thermostat](https://github.com/KartoffelToby/better_thermostat)), general climate control ([Versatile Thermostat](https://github.com/jmcollin78/versatile_thermostat)), and precise PID control ([Smart Thermostat PID](https://github.com/ScratMan/smart-thermostat-pid)). But hydronic UFH has specific requirements that none address together:

| Requirement | Generic Solutions | This Integration |
|-------------|-------------------|------------------|
| **Multi-zone heat aggregation** | Each zone fires boiler independently | Zones coordinate through shared heat request |
| **Boiler/heat pump signaling** | Basic on/off or none | Valve pre-opening, quota-aware requests |
| **EMS-ESP boiler integration** | Manual automations required | Native summer mode, DHW detection |
| **DHW priority handling** | Not supported | Blocks new heating during DHW, captures latent heat |
| **UFH thermal response** | Adapted from radiator/TRV logic | Native PID tuned for slow thermal mass |

## Key Differentiators

### Purpose-Built for Hydronic UFH

The control algorithm accounts for:

- **Slow thermal response** - PID tuning defaults optimized for concrete screed
- **Valve scheduling** - 2-hour observation periods prevent rapid cycling
- **Minimum run times** - Protects valves from wear while maintaining efficiency
- **Sensor noise filtering** - EMA smoothing handles noisy wireless sensors (Zigbee, etc.)

### Native Boiler Coordination

Multiple zones sharing one heat source need coordination. The controller:

- **Aggregates zone demands** into a single heat request signal
- **Waits for valves to open** before firing the boiler (configurable delay)
- **Manages quota intelligently** - stops requesting heat before a zone's time expires
- **Supports summer mode** - automatically enables/disables the boiler's heating circuit

### EMS-ESP Integration

For users with Bosch, Buderus, Nefit, Junkers, or Worcester boilers running [EMS-ESP](https://github.com/emsesp/EMS-ESP32):

- **Summer mode control** - Disables heating circuit when no zones need heat
- **DHW priority detection** - Blocks new heating cycles during hot water, existing zones continue circulating
- **Latent heat capture** - Zones configured as flush circuits capture residual boiler heat after DHW

### Zone Fault Isolation

Sensor failures in one zone don't bring down your heating:

- **Independent zones** - Each zone evaluates and fails separately
- **Graceful degradation** - Failed zones use last-known demand for 1 hour before fail-safe
- **Safe initialization** - No valve actions until all zones have valid temperature readings
- **Clear status reporting** - Controller and zone health visible as entities
- **PID diagnostics** - Per-zone sensors for duty cycle, error, and PID terms

### Production-Grade Engineering

- **State persistence** - All control variables survive Home Assistant restarts and crashes
- **90%+ test coverage** - Enforced minimum with 100% target for core control logic
- **Strict type checking** - Full type annotations verified by ty
- **Automated CI** - Every PR runs tests, linting (ruff), formatting, and type checks
- **HACS compliant** - Validated against hassfest and HACS requirements

## Requirements

- Home Assistant 2025.10 or newer
- A hydronic underfloor heating system with:
  - Temperature sensor per zone
  - Valve switch per zone
  - (Optional) Boiler heat request switch or summer mode control
  - (Optional) DHW active sensor for latent heat capture
  - (Optional) Window/door sensors (pauses PID integration, prevents integral windup)

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

1. **Add Integration**: Settings → Devices & Services → Add Integration → "Underfloor Heating Controller"
2. **Configure Boiler** (optional): Connect heat request switch, DHW sensor, summer mode select
3. **Add Zones**: Each zone needs a temperature sensor and valve switch
4. **Set Presets**: Configure Home/Away/Eco/Comfort/Boost temperatures per zone

## Operation Modes

| Mode | Purpose |
|------|---------|
| **Heat** | Normal PID control with zone scheduling |
| **Flush** | All valves open for circulation (no boiler firing) |
| **Cycle** | Diagnostic 8-hour rotation through zones |
| **All On** | Maximum heating - all valves open |
| **All Off** | All valves closed |
| **Off** | Controller inactive |

## Documentation

- **[Full Documentation](docs/index.md)** - Architecture, algorithms, configuration reference
- **[Control Algorithm](docs/control_algorithm.md)** - PID controller and scheduling details
- **[Fault Isolation](docs/fault_isolation.md)** - How zone failures are handled
- **[Configuration](docs/configuration.md)** - All parameters explained
- **[Tasmota Relay Configuration](docs/tasmota.md)** - Setting up Tasmota-controlled relay boards

## License

MIT License - see [LICENSE](LICENSE) for details.