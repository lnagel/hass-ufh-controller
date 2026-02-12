"""Test history query helpers."""

from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, State
from sqlalchemy.exc import OperationalError

from custom_components.ufh_controller.core.history import (
    get_observation_start,
    get_valve_position_window,
)
from custom_components.ufh_controller.recorder import (
    get_state_average,
    get_valve_position,
)


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    return hass


def mock_recorder_states(
    entity_id: str, states: list | None = None
) -> AbstractContextManager:
    """Return a context manager that patches the recorder with given states."""
    result = {entity_id: states} if states else {}
    recorder = MagicMock()
    recorder.async_add_executor_job = AsyncMock(return_value=result)
    return patch(
        "homeassistant.components.recorder.get_instance",
        return_value=recorder,
    )


def make_state(value: str, last_changed: datetime) -> MagicMock:
    """Create a mock State with the given value and last_changed."""
    state = MagicMock(spec=State)
    state.state = value
    state.last_changed = last_changed
    return state


class TestGetObservationStart:
    """Test cases for get_observation_start."""

    def test_default_2_hour_period_mid_period(self) -> None:
        """Test default 2-hour period alignment from midnight."""
        # 14:30 should align to 14:00 (7th period: 14:00-16:00)
        now = datetime(2024, 1, 15, 14, 30, 45, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_default_2_hour_period_odd_hour(self) -> None:
        """Test alignment when current hour is odd."""
        # 15:45 should align to 14:00 (still in 14:00-16:00 period)
        now = datetime(2024, 1, 15, 15, 45, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_at_period_start(self) -> None:
        """Test when already at period start."""
        now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_midnight_alignment(self) -> None:
        """Test alignment in first period after midnight."""
        now = datetime(2024, 1, 15, 1, 30, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)

    def test_at_midnight(self) -> None:
        """Test exactly at midnight."""
        now = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)

    def test_3_hour_period(self) -> None:
        """Test with 3-hour observation period."""
        # 14:30 with 3-hour period should align to 12:00 (5th period: 12:00-15:00)
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=10800)  # 3 hours
        assert result == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    def test_1_hour_period(self) -> None:
        """Test with 1-hour observation period."""
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=3600)  # 1 hour
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_fractional_2_5_hour_period(self) -> None:
        """Test with 2.5-hour (9000s) observation period."""
        # 2.5h periods: 00:00, 02:30, 05:00, 07:30, 10:00, 12:30, 15:00, ...
        # 14:30 should be in 12:30-15:00 period
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=9000)  # 2.5 hours
        assert result == datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)

    def test_fractional_1_5_hour_period(self) -> None:
        """Test with 1.5-hour (5400s) observation period."""
        # 1.5h periods: 00:00, 01:30, 03:00, 04:30, 06:00, ...
        # 14:30 should be in 13:30-15:00 period
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=5400)  # 1.5 hours
        assert result == datetime(2024, 1, 15, 13, 30, 0, tzinfo=UTC)

    def test_30_minute_period(self) -> None:
        """Test with 30-minute (1800s) observation period."""
        # 14:45 should be in 14:30-15:00 period
        now = datetime(2024, 1, 15, 14, 45, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=1800)  # 30 min
        assert result == datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

    def test_10_minute_granularity(self) -> None:
        """Test with 50-minute (3000s) observation period (UI allows 10-min steps)."""
        # 50-min periods: 00:00, 00:50, 01:40, 02:30, ...
        # At 02:45, should be in period starting at 02:30
        now = datetime(2024, 1, 15, 2, 45, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=3000)  # 50 min
        assert result == datetime(2024, 1, 15, 2, 30, 0, tzinfo=UTC)

    def test_end_of_day_truncated_period(self) -> None:
        """Test behavior at end of day when period doesn't divide evenly into 24h."""
        # With 2.5h periods, last full period starts at 22:30
        # At 23:00 we're in the 22:30-01:00 period (but it gets truncated at midnight)
        now = datetime(2024, 1, 15, 23, 0, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=9000)  # 2.5 hours
        assert result == datetime(2024, 1, 15, 22, 30, 0, tzinfo=UTC)


class TestGetValvePositionWindow:
    """Test cases for get_valve_position_window."""

    def test_symmetric_times(self) -> None:
        """Test window with equal open and close times."""
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        start, end = get_valve_position_window(
            now, valve_open_time=300, valve_close_time=180
        )

        assert end == now
        assert start == now - timedelta(seconds=480)

    def test_asymmetric_times(self) -> None:
        """Test window with different open and close times."""
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        start, end = get_valve_position_window(
            now, valve_open_time=210, valve_close_time=300
        )

        assert end == now
        assert start == now - timedelta(seconds=510)


class TestGetStateAverage:
    """Test cases for get_state_average."""

    async def test_no_state_changes_entity_on(self, mock_hass: MagicMock) -> None:
        """Test when no state changes and entity is on."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "on"
        mock_hass.states.get.return_value = mock_state

        with mock_recorder_states("switch.test"):
            result = await get_state_average(
                mock_hass, "switch.test", start, end, on_value="on"
            )

        assert result == 1.0

    async def test_no_state_changes_entity_off(self, mock_hass: MagicMock) -> None:
        """Test when no state changes and entity is off."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "off"
        mock_hass.states.get.return_value = mock_state

        with mock_recorder_states("switch.test"):
            result = await get_state_average(
                mock_hass, "switch.test", start, end, on_value="on"
            )

        assert result == 0.0

    async def test_state_changes_half_on(self, mock_hass: MagicMock) -> None:
        """Test when state is on for half the period."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        mid = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

        states = [make_state("off", start), make_state("on", mid)]

        with mock_recorder_states("switch.test", states):
            result = await get_state_average(
                mock_hass, "switch.test", start, end, on_value="on"
            )

        assert result == pytest.approx(0.5)

    async def test_zero_time_period(self, mock_hass: MagicMock) -> None:
        """Test with zero-length time period."""
        now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

        result = await get_state_average(
            mock_hass, "switch.test", now, now, on_value="on"
        )

        assert result == 0.0


class TestRecorderQueryFailure:
    """Test Recorder query failure handling - exceptions propagate to caller."""

    async def test_get_state_average_raises_on_operational_error(
        self, mock_hass: MagicMock
    ) -> None:
        """Test that get_state_average raises OperationalError when recorder fails."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=OperationalError(
                    "statement", {}, Exception("DB unavailable")
                )
            )
            mock_get_instance.return_value = mock_recorder

            with pytest.raises(OperationalError):
                await get_state_average(
                    mock_hass,
                    "switch.test",
                    start,
                    end,
                )

    async def test_get_state_average_succeeds_after_previous_failure(
        self, mock_hass: MagicMock
    ) -> None:
        """Test that failures don't affect subsequent successful queries."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "on"
        mock_hass.states.get.return_value = mock_state

        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("statement", {}, Exception("DB unavailable"))
            return {}

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(side_effect=side_effect)
            mock_get_instance.return_value = mock_recorder

            # First call should raise
            with pytest.raises(OperationalError):
                await get_state_average(mock_hass, "switch.test", start, end)

            # Second call should succeed
            result2 = await get_state_average(mock_hass, "switch.test", start, end)
            assert result2 == 1.0


class TestGetValvePosition:
    """Test cases for get_valve_position (physical ramp estimation)."""

    async def test_no_state_changes_entity_on(self, mock_hass: MagicMock) -> None:
        """Test fully open when no state changes and entity is on."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "on"
        mock_hass.states.get.return_value = mock_state

        with mock_recorder_states("switch.test"):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=210,
                valve_close_time=210,
            )

        assert result == 1.0

    async def test_no_state_changes_entity_off(self, mock_hass: MagicMock) -> None:
        """Test fully closed when no state changes and entity is off."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "off"
        mock_hass.states.get.return_value = mock_state

        with mock_recorder_states("switch.test"):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=210,
                valve_close_time=210,
            )

        assert result == 0.0

    async def test_full_ramp_up(self, mock_hass: MagicMock) -> None:
        """Test valve fully opens after being on for valve_open_time."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)  # 420s window

        # Valve was on the entire time
        with mock_recorder_states("switch.test", [make_state("on", start)]):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=210,
                valve_close_time=210,
            )

        # 420s on / 210s open_time = 2.0, clamped to 1.0
        assert result == 1.0

    async def test_partial_ramp_up(self, mock_hass: MagicMock) -> None:
        """Test valve partially open after being on for less than valve_open_time."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)  # 420s window

        # Valve was off initially, turned on 315s in
        states = [
            make_state("off", start),
            make_state("on", start + timedelta(seconds=315)),
        ]

        with mock_recorder_states("switch.test", states):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=210,
                valve_close_time=210,
            )

        # Off for 315s (position stays 0, can't go below 0)
        # Then on for 105s: 0 + 105/210 = 0.5
        assert result == pytest.approx(0.5)

    async def test_ramp_down_after_on(self, mock_hass: MagicMock) -> None:
        """Test valve closing after being turned off."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)  # 420s window

        # Valve was on for 210s, then off for 210s
        states = [
            make_state("on", start),
            make_state("off", start + timedelta(seconds=210)),
        ]

        with mock_recorder_states("switch.test", states):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=210,
                valve_close_time=210,
            )

        # On for 210s: 0 + 210/210 = 1.0 (fully open)
        # Off for 210s: 1.0 - 210/210 = 0.0 (fully closed)
        assert result == pytest.approx(0.0)

    async def test_asymmetric_open_close_times(self, mock_hass: MagicMock) -> None:
        """Test with different open and close times."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)  # 420s window

        # Valve was on for 210s (full open), then off for 210s (partial close)
        states = [
            make_state("on", start),
            make_state("off", start + timedelta(seconds=210)),
        ]

        # Closing takes 420s (twice as long as opening)
        with mock_recorder_states("switch.test", states):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=210,
                valve_close_time=420,
            )

        # On for 210s: 0 + 210/210 = 1.0 (fully open)
        # Off for 210s: 1.0 - 210/420 = 0.5 (half closed)
        assert result == pytest.approx(0.5)

    async def test_zero_valve_times(self, mock_hass: MagicMock) -> None:
        """Test that zero open/close times don't cause division by zero."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)

        # Valve on then off, both with zero times
        states = [
            make_state("on", start),
            make_state("off", start + timedelta(seconds=210)),
        ]

        with mock_recorder_states("switch.test", states):
            result = await get_valve_position(
                mock_hass,
                "switch.test",
                start,
                end,
                valve_open_time=0,
                valve_close_time=0,
            )

        # Initial position is 1.0 (first state is "on")
        # Zero open_time: ramp-up skipped, position stays 1.0
        # Zero close_time: ramp-down skipped, position stays 1.0
        assert result == 1.0

    async def test_error_propagation(self, mock_hass: MagicMock) -> None:
        """Test that OperationalError propagates to caller."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 14, 7, 0, tzinfo=UTC)

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=OperationalError(
                    "statement", {}, Exception("DB unavailable")
                )
            )
            mock_get_instance.return_value = mock_recorder

            with pytest.raises(OperationalError):
                await get_valve_position(
                    mock_hass,
                    "switch.test",
                    start,
                    end,
                    valve_open_time=210,
                    valve_close_time=210,
                )
