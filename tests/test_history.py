"""Test history query helpers."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, State

from custom_components.ufh_controller.core.history import (
    get_numeric_average,
    get_observation_start,
    get_state_average,
    get_valve_open_window,
    get_window_open_average,
)


class TestGetObservationStart:
    """Test cases for get_observation_start."""

    def test_aligned_to_even_hours_default(self) -> None:
        """Test alignment to even hours with default 2-hour period."""
        # 14:30 should align to 14:00
        now = datetime(2024, 1, 15, 14, 30, 45, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_aligned_to_even_hours_odd_hour(self) -> None:
        """Test alignment when current hour is odd."""
        # 15:45 should align to 14:00
        now = datetime(2024, 1, 15, 15, 45, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_aligned_at_period_start(self) -> None:
        """Test when already at period start."""
        now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_midnight_alignment(self) -> None:
        """Test alignment around midnight."""
        now = datetime(2024, 1, 15, 1, 30, 0, tzinfo=UTC)
        result = get_observation_start(now)
        assert result == datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)

    def test_custom_period_3_hours(self) -> None:
        """Test with 3-hour observation period."""
        # 14:30 with 3-hour period should align to 12:00
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=10800)  # 3 hours
        assert result == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    def test_custom_period_1_hour(self) -> None:
        """Test with 1-hour observation period."""
        now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=3600)  # 1 hour
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

    def test_zero_period_defaults_to_2_hours(self) -> None:
        """Test that zero period defaults to 2 hours."""
        now = datetime(2024, 1, 15, 15, 30, 0, tzinfo=UTC)
        result = get_observation_start(now, observation_period=0)
        assert result == datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)


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


class TestGetNumericAverage:
    """Test cases for get_numeric_average."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock HomeAssistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.states = MagicMock()
        return hass

    async def test_no_state_changes_current_state(self, mock_hass: MagicMock) -> None:
        """Test when no state changes but current state exists."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        mock_state = MagicMock()
        mock_state.state = "50.0"
        mock_hass.states.get.return_value = mock_state

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(return_value={})
            mock_get_instance.return_value = mock_recorder

            result = await get_numeric_average(mock_hass, "sensor.test", start, end)

        assert result == 50.0

    async def test_weighted_average(self, mock_hass: MagicMock) -> None:
        """Test time-weighted average calculation."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        mid = datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

        state1 = MagicMock(spec=State)
        state1.state = "20.0"
        state1.last_changed = start

        state2 = MagicMock(spec=State)
        state2.state = "40.0"
        state2.last_changed = mid

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                return_value={"sensor.test": [state1, state2]}
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_numeric_average(mock_hass, "sensor.test", start, end)

        # 30 min at 20 + 30 min at 40 = (20*30 + 40*30) / 60 = 30
        assert result == pytest.approx(30.0)

    async def test_invalid_state_values(self, mock_hass: MagicMock) -> None:
        """Test handling of non-numeric state values."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        state1 = MagicMock(spec=State)
        state1.state = "unavailable"
        state1.last_changed = start

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                return_value={"sensor.test": [state1]}
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_numeric_average(mock_hass, "sensor.test", start, end)

        assert result is None

    async def test_zero_time_period(self, mock_hass: MagicMock) -> None:
        """Test with zero-length time period."""
        now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)

        result = await get_numeric_average(mock_hass, "sensor.test", now, now)

        assert result is None


class TestGetWindowOpenAverage:
    """Test cases for get_window_open_average."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock HomeAssistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.states = MagicMock()
        return hass

    async def test_no_window_sensors(self, mock_hass: MagicMock) -> None:
        """Test with empty window sensor list."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        result = await get_window_open_average(mock_hass, [], start, end)

        assert result == 0.0

    async def test_multiple_sensors_max(self, mock_hass: MagicMock) -> None:
        """Test that max open time is returned from multiple sensors."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        # First sensor: off the whole time
        state1 = MagicMock()
        state1.state = "off"
        state1.last_changed = start

        # Second sensor: on the whole time
        state2 = MagicMock()
        state2.state = "on"
        state2.last_changed = start

        def mock_states_get(entity_id: str) -> MagicMock:
            if entity_id == "binary_sensor.window1":
                return state1
            return state2

        mock_hass.states.get.side_effect = mock_states_get

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()

            def mock_executor_job(func: object, *args: object) -> dict[str, list]:
                entity_id = args[3]
                if entity_id == "binary_sensor.window1":
                    return {"binary_sensor.window1": [state1]}
                return {"binary_sensor.window2": [state2]}

            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=mock_executor_job
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_window_open_average(
                mock_hass,
                ["binary_sensor.window1", "binary_sensor.window2"],
                start,
                end,
            )

        # Should return 1.0 (max of 0.0 and 1.0)
        assert result == 1.0

    async def test_returns_none_when_query_fails(self, mock_hass: MagicMock) -> None:
        """Test that get_window_open_average returns None when a query fails."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=Exception("Recorder unavailable")
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_window_open_average(
                mock_hass,
                ["binary_sensor.window1"],
                start,
                end,
            )

        assert result is None


class TestRecorderQueryFailure:
    """Test Recorder query failure handling."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock HomeAssistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.states = MagicMock()
        return hass

    async def test_get_state_average_returns_none_on_exception(
        self, mock_hass: MagicMock
    ) -> None:
        """Test that get_state_average returns None when recorder fails."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=Exception("Recorder unavailable")
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_state_average(
                mock_hass,
                "switch.test",
                start,
                end,
            )

        assert result is None

    async def test_get_state_average_returns_none_on_timeout(
        self, mock_hass: MagicMock
    ) -> None:
        """Test that get_state_average returns None on timeout."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=TimeoutError("Query timed out")
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_state_average(
                mock_hass,
                "switch.test",
                start,
                end,
            )

        assert result is None

    async def test_get_state_average_returns_none_on_db_error(
        self, mock_hass: MagicMock
    ) -> None:
        """Test that get_state_average returns None on database errors."""
        start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(
                side_effect=RuntimeError("Database connection lost")
            )
            mock_get_instance.return_value = mock_recorder

            result = await get_state_average(
                mock_hass,
                "switch.test",
                start,
                end,
            )

        assert result is None

    async def test_get_state_average_succeeds_after_exception_is_caught(
        self, mock_hass: MagicMock
    ) -> None:
        """Test that exception handling doesn't affect subsequent successful queries."""
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
                raise Exception("First call fails")  # noqa: TRY002
            return {}

        with patch(
            "homeassistant.components.recorder.get_instance"
        ) as mock_get_instance:
            mock_recorder = MagicMock()
            mock_recorder.async_add_executor_job = AsyncMock(side_effect=side_effect)
            mock_get_instance.return_value = mock_recorder

            # First call should return None
            result1 = await get_state_average(mock_hass, "switch.test", start, end)
            assert result1 is None

            # Second call should succeed
            result2 = await get_state_average(mock_hass, "switch.test", start, end)
            assert result2 == 1.0
