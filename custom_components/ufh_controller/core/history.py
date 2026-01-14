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
