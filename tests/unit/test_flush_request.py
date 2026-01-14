"""Unit tests for compute_flush_request."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ufh_controller.core.controller import compute_flush_request

# flush_until states: None, "future" (active), "expired"
FLUSH_UNTIL_FUTURE = "future"
FLUSH_UNTIL_EXPIRED = "expired"


@pytest.mark.parametrize(
    ("flush_enabled", "dhw_active", "flush_until", "any_regular_on", "expected"),
    [
        # flush_enabled=False always returns False
        (False, True, None, False, False),
        (False, True, FLUSH_UNTIL_FUTURE, False, False),
        # No DHW activity (not active, no timer) returns False
        (True, False, None, False, False),
        # DHW active + no regular ON = True
        (True, True, None, False, True),
        # DHW active + regular ON = False
        (True, True, None, True, False),
        # Post-DHW period (timer active) + no regular ON = True
        (True, False, FLUSH_UNTIL_FUTURE, False, True),
        # Post-DHW period + regular ON = False
        (True, False, FLUSH_UNTIL_FUTURE, True, False),
        # Post-DHW period expired = False
        (True, False, FLUSH_UNTIL_EXPIRED, False, False),
        # DHW active overrides expired timer
        (True, True, FLUSH_UNTIL_EXPIRED, False, True),
    ],
    ids=[
        "disabled_returns_false",
        "disabled_with_timer_returns_false",
        "no_dhw_activity_returns_false",
        "dhw_active_no_regular_returns_true",
        "dhw_active_regular_on_returns_false",
        "post_dhw_no_regular_returns_true",
        "post_dhw_regular_on_returns_false",
        "post_dhw_expired_returns_false",
        "dhw_active_overrides_expired_timer",
    ],
)
def test_compute_flush_request(
    flush_enabled: bool,
    dhw_active: bool,
    flush_until: str | None,
    any_regular_on: bool,
    expected: bool,
) -> None:
    """Test compute_flush_request with various input combinations."""
    now = datetime.now(UTC)

    # Convert flush_until marker to actual datetime
    flush_until_dt: datetime | None = None
    if flush_until == FLUSH_UNTIL_FUTURE:
        flush_until_dt = now + timedelta(minutes=5)
    elif flush_until == FLUSH_UNTIL_EXPIRED:
        flush_until_dt = now - timedelta(minutes=1)

    result = compute_flush_request(
        flush_enabled=flush_enabled,
        dhw_active=dhw_active,
        flush_until=flush_until_dt,
        any_regular_on=any_regular_on,
        now=now,
    )
    assert result is expected
