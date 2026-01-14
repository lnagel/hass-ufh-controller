"""Core control logic for Underfloor Heating Controller."""

from custom_components.ufh_controller.const import TimingParams

from .controller import (
    ControllerActions,
    ControllerConfig,
    ControllerState,
    HeatingController,
)
from .ema import apply_ema
from .history import (
    get_observation_start,
    get_valve_open_window,
)
from .pid import PIDController, PIDState
from .zone import (
    CircuitType,
    ZoneAction,
    ZoneConfig,
    ZoneRuntime,
    ZoneState,
    ZoneStatusTransition,
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
    "ZoneStatusTransition",
    "apply_ema",
    "calculate_requested_duration",
    "evaluate_zone",
    "get_observation_start",
    "get_valve_open_window",
    "should_request_heat",
]
