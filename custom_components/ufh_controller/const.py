"""Constants for Underfloor Heating Controller."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger, getLogger
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN

if TYPE_CHECKING:
    from homeassistant.core import State

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ufh_controller"

# Load version from manifest.json once at module load
MANIFEST_PATH = Path(__file__).parent / "manifest.json"
VERSION = json.loads(MANIFEST_PATH.read_text())["version"]

# Subentry types for config entry organization
SUBENTRY_TYPE_CONTROLLER = "controller"
SUBENTRY_TYPE_ZONE = "zone"


class OperationMode(StrEnum):
    """Controller operation modes."""

    HEAT = "heat"
    FLUSH = "flush"
    CYCLE = "cycle"
    ALL_ON = "all_on"
    ALL_OFF = "all_off"
    OFF = "off"


class SummerMode(StrEnum):
    """
    Boiler summer mode values.

    Controls whether the boiler's heating circuit is active:
    - AUTO: Boiler controls summer/winter mode automatically
    - WINTER: Heating circuit enabled (for UFH heating)
    - SUMMER: Heating circuit disabled (DHW only)
    """

    AUTO = "auto"
    WINTER = "winter"
    SUMMER = "summer"


class ControllerStatus(StrEnum):
    """Controller operational status for error tracking."""

    INITIALIZING = "initializing"  # Controller starting up, no updates yet
    NORMAL = "normal"  # All systems operating normally
    DEGRADED = "degraded"  # Using fallback values, some queries failing
    FAIL_SAFE = "fail_safe"  # Safety mode activated, valves closed


class ZoneStatus(StrEnum):
    """Zone operational status for fault isolation."""

    INITIALIZING = "initializing"  # Zone starting up, awaiting first successful update
    NORMAL = "normal"  # Zone operating normally with valid temperature readings
    DEGRADED = "degraded"  # Temp sensor, valve, or Recorder unavailable
    FAIL_SAFE = "fail_safe"  # No successful update for >1 hour, valve forced closed


class ValveState(StrEnum):
    """Valve entity state values."""

    ON = STATE_ON
    OFF = STATE_OFF
    UNKNOWN = STATE_UNKNOWN
    UNAVAILABLE = STATE_UNAVAILABLE

    @classmethod
    def from_ha_state(cls, state: State | None) -> ValveState:
        """Convert Home Assistant entity state to ValveState."""
        if state is None:
            return cls.UNAVAILABLE
        if state.state == STATE_UNAVAILABLE:
            return cls.UNAVAILABLE
        if state.state == STATE_ON:
            return cls.ON
        if state.state == STATE_OFF:
            return cls.OFF
        # Any other state (including STATE_UNKNOWN) -> UNKNOWN
        return cls.UNKNOWN


# Failure handling constants
FAILURE_NOTIFICATION_THRESHOLD = (
    3  # Create notification after this many consecutive failures
)
INITIALIZING_TIMEOUT = 120  # 2 minutes before fail-safe during initialization
FAIL_SAFE_TIMEOUT = 3600  # 1 hour in seconds before activating fail-safe mode

# Coordinator update intervals
INITIALIZING_UPDATE_INTERVAL = 10  # Fast updates (seconds) during initialization


class TimingDefaults(TypedDict):
    """Type for DEFAULT_TIMING dictionary."""

    observation_period: int
    min_run_time: int
    valve_open_time: int
    closing_warning_duration: int
    window_block_time: int
    controller_loop_interval: int
    flush_duration: int


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


class PresetDefaults(TypedDict):
    """Type for DEFAULT_PRESETS dictionary."""

    home: float
    away: float
    eco: float
    comfort: float
    boost: float


# Default timing parameters (in seconds unless otherwise noted)
DEFAULT_TIMING: TimingDefaults = {
    "observation_period": 7200,  # 2 hours
    "min_run_time": 540,  # 9 minutes
    "valve_open_time": 210,  # 3.5 minutes
    "closing_warning_duration": 240,  # 4 minutes
    "window_block_time": 600,  # 10 minutes - block if window open this long
    "controller_loop_interval": 60,  # PID update interval
    "flush_duration": 480,  # 8 minutes - flush duration after DHW ends
}


@dataclass
class TimingParams:
    """
    Timing parameters for zone scheduling.

    All durations are in seconds.
    """

    observation_period: int = DEFAULT_TIMING["observation_period"]
    min_run_time: int = DEFAULT_TIMING["min_run_time"]
    valve_open_time: int = DEFAULT_TIMING["valve_open_time"]
    closing_warning_duration: int = DEFAULT_TIMING["closing_warning_duration"]
    window_block_time: int = DEFAULT_TIMING["window_block_time"]
    controller_loop_interval: int = DEFAULT_TIMING["controller_loop_interval"]
    flush_duration: int = DEFAULT_TIMING["flush_duration"]


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

# Default preset temperatures (in °C)
DEFAULT_PRESETS: PresetDefaults = {
    "home": 21.0,
    "away": 16.0,
    "eco": 19.0,
    "comfort": 22.0,
    "boost": 25.0,
}

# Cycle mode configuration
DEFAULT_CYCLE_MODE_HOURS = 8

# Zone operation thresholds
DEFAULT_VALVE_OPEN_THRESHOLD = 0.85  # 85% threshold for considering valve fully open
DEFAULT_WINDOW_OPEN_THRESHOLD = 0.1  # 10% threshold for window open detection

# UI validation constraints for timing parameters
UI_TIMING_OBSERVATION_PERIOD = {"min": 1800, "max": 14400, "step": 600}
UI_TIMING_MIN_RUN_TIME = {"min": 60, "max": 1800, "step": 60}
UI_TIMING_VALVE_OPEN_TIME = {"min": 60, "max": 600, "step": 30}
UI_TIMING_CLOSING_WARNING = {"min": 60, "max": 600, "step": 30}
UI_TIMING_WINDOW_BLOCK_TIME = {"min": 0, "max": 3600, "step": 60}
UI_TIMING_CONTROLLER_LOOP_INTERVAL = {"min": 10, "max": 300, "step": 5}
UI_TIMING_FLUSH_DURATION = {"min": 0, "max": 1800, "step": 60}  # 0-30 minutes

# UI validation constraints for setpoint parameters
UI_SETPOINT_MIN = {"min": 5.0, "max": 30.0, "step": 0.1}
UI_SETPOINT_MAX = {"min": 5.0, "max": 35.0, "step": 0.1}
UI_SETPOINT_DEFAULT = {"min": 5.0, "max": 35.0, "step": 0.1}

# Temperature smoothing (EMA low-pass filter)
DEFAULT_TEMP_EMA_TIME_CONSTANT = 600  # 10 minutes in seconds

# UI validation constraints for temperature smoothing
UI_TEMP_EMA_TIME_CONSTANT = {"min": 0, "max": 1800, "step": 60}  # 0-30 minutes

# UI validation constraints for preset temperatures
UI_PRESET_TEMPERATURE = {"min": 5.0, "max": 35.0, "step": 0.5}
