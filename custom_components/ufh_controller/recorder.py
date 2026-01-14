"""
Home Assistant Recorder query helpers for Underfloor Heating Controller.

This module provides async functions that query Home Assistant's Recorder
component for historical entity states. These functions have side effects
(I/O) and belong in the integration layer, not core.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .const import DEFAULT_WINDOW_OPEN_THRESHOLD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


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
        if avg >= DEFAULT_WINDOW_OPEN_THRESHOLD:
            return True

    return False
