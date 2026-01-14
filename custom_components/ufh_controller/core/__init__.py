"""Core control logic for Underfloor Heating Controller."""

from .controller import (
    ControllerConfig,
    HeatingController,
    ZoneConfig,
    ZoneRuntime,
)
from .ema import apply_ema
from .history import (
    get_observation_start,
    get_state_average,
    get_valve_open_window,
    was_any_window_open_recently,
)
from .pid import PIDController, PIDState
from .zone import (
    CircuitType,
    ControllerState,
    TimingParams,
    ZoneAction,
    ZoneState,
    aggregate_heat_request,
    calculate_requested_duration,
    evaluate_zone,
    should_request_heat,
)

__all__ = [
    "CircuitType",
    "ControllerConfig",
    "ControllerState",
    "HeatingController",
    "PIDController",
    "PIDState",
    "TimingParams",
    "ZoneAction",
    "ZoneConfig",
    "ZoneRuntime",
    "ZoneState",
    "aggregate_heat_request",
    "apply_ema",
    "calculate_requested_duration",
    "evaluate_zone",
    "get_observation_start",
    "get_state_average",
    "get_valve_open_window",
    "should_request_heat",
    "was_any_window_open_recently",
]
