"""Test hysteresis rounding for temperature display."""

import pytest

from custom_components.ufh_controller.core.hysteresis import round_with_hysteresis


@pytest.mark.parametrize(
    ("raw", "prev", "expected", "precision", "hysteresis"),
    [
        # First reading (no previous) - standard rounding
        (20.04, None, 20.0, 0.1, 0.03),
        (20.06, None, 20.1, 0.1, 0.03),
        # Stable within hysteresis band
        (20.04, 20.0, 20.0, 0.1, 0.03),
        (20.07, 20.0, 20.0, 0.1, 0.03),
        (19.93, 20.0, 20.0, 0.1, 0.03),
        (19.96, 20.0, 20.0, 0.1, 0.03),
        (20.0, 20.0, 20.0, 0.1, 0.03),
        (20.03, 20.0, 20.0, 0.1, 0.03),
        # Crosses upper threshold
        (20.09, 20.0, 20.1, 0.1, 0.03),
        # Crosses lower threshold
        (19.91, 20.0, 19.9, 0.1, 0.03),
        # Large jumps
        (22.5, 20.0, 22.5, 0.1, 0.03),
        (18.0, 20.0, 18.0, 0.1, 0.03),
        # Custom precision (0.5°C)
        (20.3, 20.0, 20.0, 0.5, 0.1),
        (20.4, 20.0, 20.5, 0.5, 0.1),
        # Custom hysteresis (0.05)
        (20.08, 20.0, 20.0, 0.1, 0.05),
        (20.11, 20.0, 20.1, 0.1, 0.05),
        # Negative temperatures
        (-5.04, -5.0, -5.0, 0.1, 0.03),
        (-5.09, -5.0, -5.1, 0.1, 0.03),
        (-4.91, -5.0, -4.9, 0.1, 0.03),
    ],
)
def test_round_with_hysteresis(
    raw: float,
    prev: float | None,
    expected: float,
    precision: float,
    hysteresis: float,
) -> None:
    """Test hysteresis rounding with various inputs."""
    result = round_with_hysteresis(
        raw, prev, precision=precision, hysteresis=hysteresis
    )
    assert result == pytest.approx(expected)


def test_oscillation_sequence() -> None:
    """Verify hysteresis prevents flicker during oscillation around boundary."""
    readings = [20.04, 20.06, 20.04, 20.07, 20.09, 20.06, 20.04]
    expected = [20.0, 20.0, 20.0, 20.0, 20.1, 20.1, 20.1]

    display = None
    for raw, exp in zip(readings, expected, strict=True):
        display = round_with_hysteresis(raw, display)
        assert display == pytest.approx(exp)
