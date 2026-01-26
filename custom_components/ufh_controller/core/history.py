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
