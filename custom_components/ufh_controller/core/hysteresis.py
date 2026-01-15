"""Hysteresis rounding for temperature display."""

_PRECISION: float = 0.1  # Matches HA's PRECISION_TENTHS
_HYSTERESIS: float = 0.0299  # Margin to prevent flicker


def round_with_hysteresis(raw: float, prev: float | None) -> float:
    """
    Round temperature to 0.1°C with hysteresis to prevent display flicker.

    Raw must cross the boundary by 0.03°C before the display changes.
    E.g., display at 20.0 requires raw >= 20.08 to show 20.1.
    """
    target = round(raw / _PRECISION) * _PRECISION

    if prev is None:
        return target

    if abs(target - prev) < _PRECISION / 2:
        return prev

    if target > prev:
        if raw >= prev + _PRECISION / 2 + _HYSTERESIS:
            return target
        return prev

    if raw <= prev - _PRECISION / 2 - _HYSTERESIS:
        return target
    return prev
