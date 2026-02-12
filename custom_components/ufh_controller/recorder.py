"""
Home Assistant Recorder query helpers for Underfloor Heating Controller.

This module provides async functions that query Home Assistant's Recorder
component for historical entity states. These functions have side effects
(I/O) and belong in the integration layer, not core.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components import recorder as ha_recorder
from homeassistant.components.recorder.history import state_changes_during_period

from .const import DEFAULT_WINDOW_OPEN_THRESHOLD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State


async def _query_entity_states(
    hass: HomeAssistant,
    entity_id: str,
    start: datetime,
    end: datetime,
) -> list[State] | None:
    """Query recorder for entity state changes, returning None if empty."""
    states = await ha_recorder.get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        start,
        end,
        entity_id,
    )

    entity_states = states.get(entity_id)
    return entity_states if entity_states else None


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
    total_time = (end - start).total_seconds()
    if total_time <= 0:
        return 0.0

    entity_states = await _query_entity_states(hass, entity_id, start, end)
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


async def get_valve_position(  # noqa: PLR0913
    hass: HomeAssistant,
    entity_id: str,
    start: datetime,
    end: datetime,
    valve_open_time: int,
    valve_close_time: int,
    on_value: str = "on",
) -> float:
    """
    Estimate physical valve position by walking through state change history.

    Models thermal-wax actuator ramp-up (when powered) and ramp-down
    (passive wax cooling + spring return) to estimate how open the valve
    physically is at the end of the window.

    Args:
        hass: Home Assistant instance.
        entity_id: Entity ID to query.
        start: Start of the time period.
        end: End of the time period.
        valve_open_time: Time in seconds for valve to fully open.
        valve_close_time: Time in seconds for valve to fully close.
        on_value: State value considered "on" (default "on").

    Returns:
        Valve position as a ratio (0.0 to 1.0).

    Raises:
        SQLAlchemyError: If Recorder query fails.

    """
    entity_states = await _query_entity_states(hass, entity_id, start, end)
    if not entity_states:
        # No state changes - check current state
        current_state = hass.states.get(entity_id)
        if current_state and current_state.state == on_value:
            return 1.0
        return 0.0

    # Initial position based on first recorded state
    position = 1.0 if entity_states[0].state == on_value else 0.0

    # Walk through state change segments
    for i, state in enumerate(entity_states):
        segment_start = max(state.last_changed, start)
        if i + 1 < len(entity_states):
            segment_end = entity_states[i + 1].last_changed
        else:
            segment_end = end

        duration = (segment_end - segment_start).total_seconds()

        if state.state == on_value:
            # Valve powering open: ramp up
            if valve_open_time > 0:
                position = min(1.0, position + duration / valve_open_time)
        # Valve closing passively: ramp down
        elif valve_close_time > 0:
            position = max(0.0, position - duration / valve_close_time)

    return position


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
