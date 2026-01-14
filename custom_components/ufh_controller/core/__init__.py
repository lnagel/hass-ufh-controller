"""Core control logic for Underfloor Heating Controller."""

from custom_components.ufh_controller.const import TimingParams

from .controller import (
    ControllerActions,
    ControllerConfig,
    ControllerState,
    HeatingController,
    aggregate_heat_request,
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
    ZoneAction,
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
    calculate_requested_duration,
    evaluate_zone,
    should_request_heat,
)

__all__ = [
    "CircuitType",
    "ControllerActions",
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
