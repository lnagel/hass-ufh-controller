"""
Historical state query helpers for Underfloor Heating Controller.

This module provides functions for querying historical entity states
from Home Assistant's Recorder component for time-windowed calculations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from custom_components.ufh_controller.const import DEFAULT_TIMING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def get_observation_start(
    now: datetime, observation_period: int = DEFAULT_TIMING["observation_period"]
) -> datetime:
    """
    Get the start time of the current observation period.

    Observation periods are aligned to even hours (00:00, 02:00, 04:00, etc.)
    for a 2-hour default period.

    Args:
        now: Current datetime.
        observation_period: Period duration in seconds (default 7200 = 2 hours).

    Returns:
        Start datetime of the current observation period.

    """
    period_hours = observation_period // 3600
    if period_hours <= 0:
        period_hours = 2

    hour = now.hour
    period_hour = hour - (hour % period_hours)
    return now.replace(hour=period_hour, minute=0, second=0, microsecond=0)


def get_valve_open_window(
    now: datetime, valve_open_time: int = DEFAULT_TIMING["valve_open_time"]
) -> tuple[datetime, datetime]:
    """
    Get the time window for valve open detection.

    Args:
        now: Current datetime.
        valve_open_time: Detection window in seconds (default 210 = 3.5 minutes).

    Returns:
        Tuple of (start, end) datetime for valve open detection.

    """
    start = now - timedelta(seconds=valve_open_time)
    return (start, now)


async def get_state_average(
    hass: HomeAssistant,
    entity_id: str,
    start: datetime,
    end: datetime,
    on_value: str = "on",
) -> float:
    """
    Calculate time-weighted average of a binary state over a period.

    Queries the Recorder for state changes and calculates what fraction
    of the time the entity was in the "on" state.

    Args:
        hass: Home Assistant instance.
        entity_id: Entity ID to query.
        start: Start of the time period.
        end: End of the time period.
        on_value: State value considered "on" (default "on").

    Returns:
        Average as a ratio (0.0 to 1.0).

    Raises:
        SQLAlchemyError: If Recorder query fails.

    """
    # Import here to allow testing without HA recorder
    from homeassistant.components.recorder import get_instance  # noqa: PLC0415
    from homeassistant.components.recorder.history import (  # noqa: PLC0415
        state_changes_during_period,
    )

    total_time = (end - start).total_seconds()
    if total_time <= 0:
        return 0.0

    # Query recorder for state changes
    states = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        start,
        end,
        entity_id,
    )

    entity_states = states.get(entity_id)
    if not entity_states:
        # No state changes - check current state
        current_state = hass.states.get(entity_id)
        if current_state and current_state.state == on_value:
            return 1.0
        return 0.0

    # Calculate time-weighted average
    total_on_time = 0.0

    for i, state in enumerate(entity_states):
        state_start = max(state.last_changed, start)
        if i + 1 < len(entity_states):
            state_end = entity_states[i + 1].last_changed
        else:
            state_end = end

        duration = (state_end - state_start).total_seconds()

        if state.state == on_value:
            total_on_time += duration

    return total_on_time / total_time


async def get_window_open_average(
    hass: HomeAssistant,
    window_sensors: list[str],
    start: datetime,
    end: datetime,
) -> float:
    """
    Calculate the average "open" time across multiple window sensors.

    If any window sensor is open, it counts as open time.

    Args:
        hass: Home Assistant instance.
        window_sensors: List of window/door sensor entity IDs.
        start: Start of the time period.
        end: End of the time period.

    Returns:
        Average open ratio (0.0 to 1.0).

    Raises:
        SQLAlchemyError: If Recorder query fails.

    """
    if not window_sensors:
        return 0.0

    # Get average for each sensor and take the max (any open = blocked)
    max_open = 0.0
    for sensor_id in window_sensors:
        avg = await get_state_average(hass, sensor_id, start, end, on_value="on")
        max_open = max(max_open, avg)

    return max_open


async def was_any_window_open_recently(
    hass: HomeAssistant,
    window_sensors: list[str],
    now: datetime,
    lookback_seconds: int,
) -> bool:
    """
    Check if any window was open within the recent lookback period.

    This is used to determine if PID control should be paused after a window
    opening event. The lookback includes the time window was open PLUS the
    configured delay period.

    Args:
        hass: Home Assistant instance.
        window_sensors: List of window/door sensor entity IDs.
        now: Current datetime.
        lookback_seconds: How far back to check for window openings.

    Returns:
        True if any window was open within the lookback period.

    Raises:
        SQLAlchemyError: If Recorder query fails.

    """
    if not window_sensors:
        return False

    # Check each sensor for any open time in the recent window
    start = now - timedelta(seconds=lookback_seconds)
    for sensor_id in window_sensors:
        avg = await get_state_average(hass, sensor_id, start, now, on_value="on")
        if avg > 0.0:  # Any open time at all = pause PID
            return True

    return False
