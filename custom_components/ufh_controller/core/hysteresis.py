"""Hysteresis rounding for temperature display."""

# Display precision for climate entity (matches HA's PRECISION_TENTHS)
DISPLAY_PRECISION: float = 0.1

# Hysteresis margin to prevent flicker at quantization boundaries
HYSTERESIS_MARGIN: float = 0.03


def round_with_hysteresis(
    raw: float,
    prev_display: float | None,
    precision: float = DISPLAY_PRECISION,
    hysteresis: float = HYSTERESIS_MARGIN,
) -> float:
    """
    Round temperature with hysteresis to prevent flicker at quantization boundaries.

    Without hysteresis, a temperature oscillating around 20.05°C would cause the
    displayed value to flicker between 20.0 and 20.1. With hysteresis, the value
    must cross the boundary by a margin before the display changes.

    Example with precision=0.1, hysteresis=0.03:
    - Current display: 20.0°C
    - Raw must reach 20.08°C to change display to 20.1°C
    - Raw must drop to 19.92°C to change display to 19.9°C
    - Values between 19.92 and 20.08 keep the display at 20.0°C

    Args:
        raw: Raw temperature value (from EMA-smoothed reading).
        prev_display: Previous displayed (quantized) value, or None on first call.
        precision: Quantization step size (default 0.1°C).
        hysteresis: Extra margin required to cross a boundary (default 0.03°C).

    Returns:
        Quantized temperature value with hysteresis applied.

    """
    # Standard rounding to get target value
    target = round(raw / precision) * precision

    # No previous value - just return rounded value
    if prev_display is None:
        return target

    # If target equals previous (within floating point tolerance), keep it
    if abs(target - prev_display) < precision / 2:
        return prev_display

    # Check if raw has crossed the boundary by enough margin
    if target > prev_display:
        # Moving up: require raw >= upper_boundary + hysteresis
        boundary = prev_display + precision / 2
        if raw >= boundary + hysteresis:
            return target
        return prev_display
    # Moving down: require raw <= lower_boundary - hysteresis
    boundary = prev_display - precision / 2
    if raw <= boundary - hysteresis:
        return target
    return prev_display
