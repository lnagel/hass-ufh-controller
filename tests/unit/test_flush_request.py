"""Unit tests for compute_flush_request."""

from datetime import UTC, datetime, timedelta

from custom_components.ufh_controller.core.controller import compute_flush_request


class TestComputeFlushRequest:
    """Test cases for compute_flush_request."""

    def test_disabled_returns_false(self) -> None:
        """When flush_enabled is False, always returns False."""
        now = datetime.now(UTC)
        assert (
            compute_flush_request(
                flush_enabled=False,
                dhw_active=True,
                flush_until=None,
                any_regular_on=False,
                now=now,
            )
            is False
        )

    def test_no_dhw_activity_returns_false(self) -> None:
        """When no DHW activity (active or recent), returns False."""
        now = datetime.now(UTC)
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=False,
                flush_until=None,
                any_regular_on=False,
                now=now,
            )
            is False
        )

    def test_dhw_active_no_regular_on_returns_true(self) -> None:
        """DHW active + no regular circuits = flush request."""
        now = datetime.now(UTC)
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=True,
                flush_until=None,
                any_regular_on=False,
                now=now,
            )
            is True
        )

    def test_dhw_active_regular_on_returns_false(self) -> None:
        """DHW active but regular circuits ON = no flush request."""
        now = datetime.now(UTC)
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=True,
                flush_until=None,
                any_regular_on=True,
                now=now,
            )
            is False
        )

    def test_post_dhw_period_no_regular_on_returns_true(self) -> None:
        """In post-DHW period + no regular circuits = flush request."""
        now = datetime.now(UTC)
        flush_until = now + timedelta(minutes=5)
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=False,
                flush_until=flush_until,
                any_regular_on=False,
                now=now,
            )
            is True
        )

    def test_post_dhw_period_regular_on_returns_false(self) -> None:
        """In post-DHW period but regular circuits ON = no flush request."""
        now = datetime.now(UTC)
        flush_until = now + timedelta(minutes=5)
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=False,
                flush_until=flush_until,
                any_regular_on=True,
                now=now,
            )
            is False
        )

    def test_post_dhw_period_expired_returns_false(self) -> None:
        """Post-DHW period expired = no flush request."""
        now = datetime.now(UTC)
        flush_until = now - timedelta(minutes=1)  # Expired
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=False,
                flush_until=flush_until,
                any_regular_on=False,
                now=now,
            )
            is False
        )

    def test_dhw_active_overrides_expired_flush_until(self) -> None:
        """DHW active takes precedence even if flush_until is expired."""
        now = datetime.now(UTC)
        flush_until = now - timedelta(minutes=1)  # Expired
        assert (
            compute_flush_request(
                flush_enabled=True,
                dhw_active=True,  # Still active
                flush_until=flush_until,
                any_regular_on=False,
                now=now,
            )
            is True
        )
