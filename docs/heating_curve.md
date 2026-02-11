# Heating Curve

Weather compensation is standard practice for hydronic UFH systems (EN 15316-2, EN 15232) and ensures optimal comfort
while maximizing efficiency. The heating curve feature dynamically adjusts the supply target temperature based on
outdoor conditions.

## How It Works

The heating curve uses two-point linear interpolation between design points:

```
supply_target = supply_warm + (supply_cold - supply_warm) ×
                (outdoor_warm - outdoor_temp) / (outdoor_warm - outdoor_cold)
```

The result is clamped to `[supply_warm, supply_cold]` when outdoor temp is outside the design range.

## Example

With default parameters (outdoor: 15°C→-10°C, supply: 25°C→45°C):

| Outdoor Temp | Supply Target |
|--------------|---------------|
| 15°C (warm)  | 25°C          |
| 2.5°C (mid)  | 35°C          |
| -10°C (cold) | 45°C          |
| 20°C (above) | 25°C (clamped)|
| -20°C (below)| 45°C (clamped)|

## Configuration

The heating curve requires an outdoor temperature sensor. When configured, the controller reads the outdoor temperature once per update cycle and calculates the appropriate supply target.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `outdoor_temp_entity` | None | Outdoor temperature sensor (enables heating curve) |
| `outdoor_temp_warm` | 15.0°C | Outdoor temp at warm design point |
| `outdoor_temp_cold` | -10.0°C | Outdoor temp at cold design point |
| `supply_temp_warm` | 25.0°C | Supply target at warm point |
| `supply_temp_cold` | 45.0°C | Supply target at cold point |
| `supply_target_temp` | 40.0°C | Fallback when outdoor sensor unavailable |

See [Configuration](configuration.md#heat-accounting) for detailed parameter documentation.

## Behavior

**Without outdoor sensor configured:** The system uses the fixed `supply_target_temp` value (default 40°C).

**With outdoor sensor configured:** The system calculates a dynamic supply target using the heating curve formula. If the outdoor sensor becomes unavailable at runtime, the system falls back to `supply_target_temp`.

**Invalid configuration:** If `outdoor_temp_warm` is not greater than `outdoor_temp_cold`, a warning is logged and the system uses `supply_target_temp` as fallback.

## Supply Target Sensor

When an outdoor temperature sensor is configured, a "Supply Target" sensor entity is created that exposes the calculated supply target temperature. This allows monitoring the heating curve output in Home Assistant dashboards and automations.

## Integration with Heat Accounting

When both heating curve and [heat accounting](heat_accounting.md) are enabled, the dynamic supply target from the heating curve is used for supply coefficient calculation. This provides more accurate quota normalization across varying outdoor conditions.
