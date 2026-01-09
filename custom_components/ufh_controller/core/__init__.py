"""Core control logic for UFH Controller."""

from .controller import (
    ControllerConfig,
    HeatingController,
    ZoneConfig,
    ZoneRuntime,
)
from .history import (
    get_observation_start,
    get_state_average,
    get_valve_open_window,
    get_window_open_average,
)
from .pid import PIDController, PIDOutput, PIDState
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
    "PIDOutput",
    "PIDState",
    "TimingParams",
    "ZoneAction",
    "ZoneConfig",
    "ZoneRuntime",
    "ZoneState",
    "aggregate_heat_request",
    "calculate_requested_duration",
    "evaluate_zone",
    "get_observation_start",
    "get_state_average",
    "get_valve_open_window",
    "get_window_open_average",
    "should_request_heat",
]
