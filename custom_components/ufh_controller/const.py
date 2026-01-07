"""Constants for UFH Controller."""

from enum import StrEnum
from logging import Logger, getLogger
from typing import TypedDict

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ufh_controller"
SUBENTRY_TYPE_CONTROLLER = "controller"
SUBENTRY_TYPE_ZONE = "zone"

# Platforms to set up
PLATFORMS: list[str] = [
    "climate",
    "sensor",
    "binary_sensor",
    "select",
    "switch",
]


class OperationMode(StrEnum):
    """Controller operation modes."""

    AUTO = "auto"
    FLUSH = "flush"
    CYCLE = "cycle"
    ALL_ON = "all_on"
    ALL_OFF = "all_off"
    DISABLED = "disabled"


class TimingDefaults(TypedDict):
    """Type for DEFAULT_TIMING dictionary."""

    observation_period: int
    duty_cycle_window: int
    min_run_time: int
    valve_open_time: int
    closing_warning_duration: int
    window_block_threshold: float
    controller_loop_interval: int


class PIDDefaults(TypedDict):
    """Type for DEFAULT_PID dictionary."""

    kp: float
    ki: float
    kd: float
    integral_min: float
    integral_max: float


class SetpointDefaults(TypedDict):
    """Type for DEFAULT_SETPOINT dictionary."""

    min: float
    max: float
    step: float
    default: float


# Default timing parameters (in seconds unless otherwise noted)
DEFAULT_TIMING: TimingDefaults = {
    "observation_period": 7200,  # 2 hours
    "duty_cycle_window": 3600,  # 1 hour
    "min_run_time": 540,  # 9 minutes
    "valve_open_time": 210,  # 3.5 minutes
    "closing_warning_duration": 240,  # 4 minutes
    "window_block_threshold": 0.05,  # 5% (ratio, not percentage)
    "controller_loop_interval": 60,  # PID update interval
}

# Default PID controller parameters
DEFAULT_PID: PIDDefaults = {
    "kp": 50.0,
    "ki": 0.001,
    "kd": 0.0,
    "integral_min": 0.0,
    "integral_max": 100.0,
}

# Default setpoint configuration
DEFAULT_SETPOINT: SetpointDefaults = {
    "min": 16.0,
    "max": 28.0,
    "step": 0.5,
    "default": 21.0,
}

# Cycle mode configuration
DEFAULT_CYCLE_MODE_HOURS = 8

# Zone operation thresholds
DEFAULT_VALVE_OPEN_THRESHOLD = 0.85  # 85% threshold for considering valve fully open

# Window centering for duty cycle calculation
DEFAULT_WINDOW_CENTER_MINUTE = 30

# UI validation constraints for timing parameters
UI_TIMING_OBSERVATION_PERIOD = {"min": 1800, "max": 14400, "step": 600}
UI_TIMING_DUTY_CYCLE_WINDOW = {"min": 600, "max": 7200, "step": 300}
UI_TIMING_MIN_RUN_TIME = {"min": 60, "max": 1800, "step": 60}
UI_TIMING_VALVE_OPEN_TIME = {"min": 60, "max": 600, "step": 30}
UI_TIMING_CLOSING_WARNING = {"min": 60, "max": 600, "step": 30}
UI_TIMING_WINDOW_BLOCK_THRESHOLD = {"min": 0, "max": 1, "step": 0.01}
UI_TIMING_CONTROLLER_LOOP_INTERVAL = {"min": 10, "max": 300, "step": 5}

# UI validation constraints for setpoint parameters
UI_SETPOINT_MIN = {"min": 5.0, "max": 30.0, "step": 0.1}
UI_SETPOINT_MAX = {"min": 5.0, "max": 35.0, "step": 0.1}
UI_SETPOINT_DEFAULT = {"min": 5.0, "max": 35.0, "step": 0.1}
