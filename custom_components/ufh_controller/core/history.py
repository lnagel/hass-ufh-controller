"""
Pure datetime calculation helpers for observation periods.

This module provides side-effect-free functions for calculating
time windows used in quota-based scheduling.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.ufh_controller.const import DEFAULT_TIMING


def get_observation_start(
    now: datetime, observation_period: int = DEFAULT_TIMING["observation_period"]
) -> datetime:
    """
    Get the start time of the current observation period.

    Observation periods are aligned to midnight and use the exact configured
    duration. For example, with a 2.5-hour (9000s) period, periods start at
    00:00, 02:30, 05:00, 07:30, etc.

    Args:
        now: Current datetime.
        observation_period: Period duration in seconds (default 7200 = 2 hours).

    Returns:
        Start datetime of the current observation period.

    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = (now - midnight).total_seconds()
    period_index = int(seconds_since_midnight // observation_period)
    return midnight + timedelta(seconds=period_index * observation_period)


def get_valve_position_window(
    now: datetime,
    valve_open_time: int,
    valve_close_time: int,
) -> tuple[datetime, datetime]:
    """
    Get the time window for valve position estimation.

    The window spans both open and close times to provide enough history
    to estimate position through both opening and closing transitions.

    Args:
        now: Current datetime.
        valve_open_time: Time for valve to fully open in seconds.
        valve_close_time: Time for valve to fully close in seconds.

    Returns:
        Tuple of (start, end) datetime for valve position detection.

    """
    start = now - timedelta(seconds=valve_open_time + valve_close_time)
    return (start, now)
