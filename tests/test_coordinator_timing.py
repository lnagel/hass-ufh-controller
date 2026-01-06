"""Tests for coordinator timing alignment utility."""

from datetime import UTC, datetime, timedelta

from custom_components.ufh_controller.coordinator import calculate_aligned_interval


class TestCalculateAlignedInterval:
    """Tests for calculate_aligned_interval function."""

    def test_mid_interval_60s(self) -> None:
        """Test calculation when in middle of a 60s interval."""
        # 12:30:30 -> next slot at 12:31:00 -> 30 seconds
        now = datetime(2024, 1, 15, 12, 30, 30, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=30)

    def test_near_slot_boundary_60s(self) -> None:
        """Test calculation when near end of a 60s interval."""
        # 12:30:55 -> next slot at 12:31:00 -> 5 seconds
        now = datetime(2024, 1, 15, 12, 30, 55, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=5)

    def test_start_of_minute_60s(self) -> None:
        """Test calculation at exact minute boundary."""
        # 12:30:00 -> next slot at 12:31:00 -> 60 seconds
        now = datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=60)

    def test_minimum_delay_enforced(self) -> None:
        """Test that minimum 1 second delay is enforced."""
        # 12:30:59.5 -> next slot at 12:31:00 -> 0.5 seconds -> enforced to 1
        now = datetime(2024, 1, 15, 12, 30, 59, 500000, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=1)

    def test_30s_interval_mid_slot(self) -> None:
        """Test 30s interval in middle of slot."""
        # 12:30:15 -> next slot at 12:30:30 -> 15 seconds
        now = datetime(2024, 1, 15, 12, 30, 15, tzinfo=UTC)
        result = calculate_aligned_interval(now, 30)
        assert result == timedelta(seconds=15)

    def test_30s_interval_second_half(self) -> None:
        """Test 30s interval in second half of minute."""
        # 12:30:45 -> next slot at 12:31:00 -> 15 seconds
        now = datetime(2024, 1, 15, 12, 30, 45, tzinfo=UTC)
        result = calculate_aligned_interval(now, 30)
        assert result == timedelta(seconds=15)

    def test_midnight_alignment(self) -> None:
        """Test alignment works correctly around midnight."""
        # 23:59:30 -> next slot at 00:00:00 -> 30 seconds
        now = datetime(2024, 1, 15, 23, 59, 30, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=30)

    def test_just_after_midnight(self) -> None:
        """Test alignment just after midnight."""
        # 00:00:15 -> next slot at 00:01:00 -> 45 seconds
        now = datetime(2024, 1, 15, 0, 0, 15, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=45)

    def test_at_midnight(self) -> None:
        """Test alignment exactly at midnight."""
        # 00:00:00 -> next slot at 00:01:00 -> 60 seconds
        now = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        assert result == timedelta(seconds=60)

    def test_with_microseconds(self) -> None:
        """Test calculation handles microseconds correctly."""
        # 12:30:30.123456 -> next slot at 12:31:00 -> ~29.88 seconds
        now = datetime(2024, 1, 15, 12, 30, 30, 123456, tzinfo=UTC)
        result = calculate_aligned_interval(now, 60)
        expected = timedelta(seconds=29, microseconds=876544)
        assert result == expected

    def test_120s_interval(self) -> None:
        """Test with 2 minute interval."""
        # 12:31:30 -> next even minute slot at 12:32:00 -> 30 seconds
        now = datetime(2024, 1, 15, 12, 31, 30, tzinfo=UTC)
        result = calculate_aligned_interval(now, 120)
        assert result == timedelta(seconds=30)

    def test_120s_interval_odd_minute(self) -> None:
        """Test 2 minute interval during odd minute."""
        # 12:33:00 -> next even minute slot at 12:34:00 -> 60 seconds
        now = datetime(2024, 1, 15, 12, 33, 0, tzinfo=UTC)
        result = calculate_aligned_interval(now, 120)
        assert result == timedelta(seconds=60)

    def test_alignment_consistency(self) -> None:
        """Test that sequential times align to expected slots."""
        # All times between 12:30:00 and 12:31:00 should align to 12:31:00
        for second in range(60):
            now = datetime(2024, 1, 15, 12, 30, second, tzinfo=UTC)
            result = calculate_aligned_interval(now, 60)
            expected_seconds = 60 - second if second > 0 else 60
            # Account for minimum 1 second
            expected_seconds = max(1, expected_seconds)
            assert result.total_seconds() == expected_seconds, (
                f"Failed for second={second}"
            )
