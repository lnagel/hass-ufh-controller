"""Test history query helpers."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, State
from sqlalchemy.exc import OperationalError

from custom_components.ufh_controller.core.history import (
    get_observation_start,
    get_valve_open_window,
)
from custom_components.ufh_controller.recorder import get_state_average


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


class TestGetValveOpenWindow:
    """Test cases for get_valve_open_window."""

    def test_default_window(self) -> None:
        """Test default 3.5 minute window."""
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        start, end = get_valve_open_window(now)

        assert end == now
        assert start == now - timedelta(seconds=210)

    def test_custom_window(self) -> None:
        """Test custom window duration."""
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        start, end = get_valve_open_window(now, valve_open_time=300)

        assert end == now
        assert start == now - timedelta(seconds=300)


class TestGetStateAverage:
    """Test cases for get_state_average."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock HomeAssistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.states = MagicMock()
        return hass

    async def test_no_state_changes_entity_on(self, mock_hass: MagicMock) -> None:
        """Test when no state changes and entity is on."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "on"
        mock_hass.states.get.return_value = mock_state

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(return_value={})
            mock_get_instance.return_value = mock_recorder

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

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(return_value={})
            mock_get_instance.return_value = mock_recorder

            result = await get_state_average(
                mock_hass, "switch.test", start, end, on_value="on"
            )

        assert result == 0.0

    async def test_state_changes_half_on(self, mock_hass: MagicMock) -> None:
        """Test when state is on for half the period."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        mid = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

        state1 = MagicMock(spec=State)
        state1.state = "off"
        state1.last_changed = start

        state2 = MagicMock(spec=State)
        state2.state = "on"
        state2.last_changed = mid

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                return_value={"switch.test": [state1, state2]}
            )
            mock_get_instance.return_value = mock_recorder

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

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock HomeAssistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.states = MagicMock()
        return hass

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
