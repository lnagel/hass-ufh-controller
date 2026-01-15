"""Test hysteresis rounding for temperature display."""

import pytest

from custom_components.ufh_controller.core.hysteresis import round_with_hysteresis


@pytest.mark.parametrize(
    ("raw", "prev", "expected"),
    [
        # First reading - standard rounding
        (20.04, None, 20.0),
        (20.06, None, 20.1),
        # Stable within hysteresis band
        (20.04, 20.0, 20.0),
        (20.07, 20.0, 20.0),
        (19.93, 20.0, 20.0),
        (19.96, 20.0, 20.0),
        (20.0, 20.0, 20.0),
        (20.03, 20.0, 20.0),
        # Crosses upper threshold
        (20.09, 20.0, 20.1),
        (23.98, 23.9, 24.0),
        # Crosses lower threshold
        (19.91, 20.0, 19.9),
        (23.92, 24.0, 23.9),
        # Large jumps
        (22.5, 20.0, 22.5),
        (18.0, 20.0, 18.0),
        # Negative temperatures
        (-5.04, -5.0, -5.0),
        (-5.09, -5.0, -5.1),
        (-4.91, -5.0, -4.9),
    ],
)
def test_round_with_hysteresis(raw: float, prev: float | None, expected: float) -> None:
    """Test hysteresis rounding with various inputs."""
    assert round_with_hysteresis(raw, prev) == pytest.approx(expected)


def test_oscillation_sequence() -> None:
    """Verify hysteresis prevents flicker during oscillation around boundary."""
    readings = [20.04, 20.06, 20.04, 20.07, 20.09, 20.06, 20.04]
    expected = [20.0, 20.0, 20.0, 20.0, 20.1, 20.1, 20.1]

    display = None
    for raw, exp in zip(readings, expected, strict=True):
        display = round_with_hysteresis(raw, display)
        assert display == pytest.approx(exp)
