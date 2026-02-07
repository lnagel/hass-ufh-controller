"""Unit tests for sensor icon functions."""

import pytest

from custom_components.ufh_controller.const import (
    ICON_GAUGE_THRESHOLDS,
    ICON_PID_ERROR_THRESHOLD,
)
from custom_components.ufh_controller.sensor import (
    _gauge_icon,
    _numeric_icon,
    _pid_error_icon,
)


@pytest.mark.parametrize(
    ("value", "expected_icon"),
    [
        (None, "mdi:gauge-empty"),
        (0.0, "mdi:gauge-empty"),
        (ICON_GAUGE_THRESHOLDS[0] - 0.1, "mdi:gauge-empty"),
        (ICON_GAUGE_THRESHOLDS[0], "mdi:gauge-low"),
        (ICON_GAUGE_THRESHOLDS[1] - 0.1, "mdi:gauge-low"),
        (ICON_GAUGE_THRESHOLDS[1], "mdi:gauge"),
        (ICON_GAUGE_THRESHOLDS[2] - 0.1, "mdi:gauge"),
        (ICON_GAUGE_THRESHOLDS[2], "mdi:gauge-full"),
        (100.0, "mdi:gauge-full"),
        (200.0, "mdi:gauge-full"),
    ],
)
def test_gauge_icon(value: float | None, expected_icon: str) -> None:
    """Test _gauge_icon returns correct icon for value."""
    assert _gauge_icon(value) == expected_icon


@pytest.mark.parametrize(
    ("value", "expected_icon"),
    [
        (None, "mdi:thermometer-off"),
        (1.0, "mdi:thermometer-plus"),
        (ICON_PID_ERROR_THRESHOLD + 0.01, "mdi:thermometer-plus"),
        (-1.0, "mdi:thermometer-minus"),
        (-ICON_PID_ERROR_THRESHOLD - 0.01, "mdi:thermometer-minus"),
        (0.0, "mdi:thermometer-check"),
        (ICON_PID_ERROR_THRESHOLD - 0.01, "mdi:thermometer-check"),
        (-ICON_PID_ERROR_THRESHOLD + 0.01, "mdi:thermometer-check"),
    ],
)
def test_pid_error_icon(value: float | None, expected_icon: str) -> None:
    """Test _pid_error_icon returns correct icon for value."""
    assert _pid_error_icon(value) == expected_icon


@pytest.mark.parametrize(
    ("value", "expected_icon"),
    [
        (None, "mdi:checkbox-blank-outline"),
        (-1, "mdi:numeric-0-box-outline"),
        (0, "mdi:numeric-0-box-outline"),
        (1, "mdi:numeric-1-box-outline"),
        (5, "mdi:numeric-5-box-outline"),
        (9, "mdi:numeric-9-box-outline"),
        (10, "mdi:numeric-10-box-outline"),
        (11, "mdi:numeric-9-plus-box-outline"),
        (99, "mdi:numeric-9-plus-box-outline"),
    ],
)
def test_numeric_icon(value: float | None, expected_icon: str) -> None:
    """Test _numeric_icon returns correct icon for value."""
    assert _numeric_icon(value) == expected_icon
