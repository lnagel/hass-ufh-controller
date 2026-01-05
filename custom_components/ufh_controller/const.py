"""Constants for UFH Controller."""

from enum import StrEnum
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ufh_controller"

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


# Default timing parameters (in seconds unless otherwise noted)
DEFAULT_TIMING = {
    "observation_period": 7200,  # 2 hours
    "duty_cycle_window": 3600,  # 1 hour
    "min_run_time": 540,  # 9 minutes
    "valve_open_time": 210,  # 3.5 minutes
    "closing_warning_duration": 240,  # 4 minutes
    "window_block_threshold": 0.05,  # 5% (ratio, not percentage)
}

# Default PID controller parameters
DEFAULT_PID = {
    "kp": 50.0,
    "ki": 0.05,
    "kd": 0.0,
    "integral_min": 0.0,
    "integral_max": 100.0,
}

# Default setpoint configuration
DEFAULT_SETPOINT = {
    "min": 16.0,
    "max": 28.0,
    "step": 0.5,
    "default": 21.0,
}

# Controller loop interval in seconds
CONTROLLER_LOOP_INTERVAL = 60
