"""Base coordinator with timestamp tracking and persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_DataT = TypeVar("_DataT")


class TimestampCoordinator(DataUpdateCoordinator[_DataT]):
    """
    DataUpdateCoordinator with timestamp tracking and persistence.

    This base class extends DataUpdateCoordinator to automatically track and persist
    the timestamp of the last successful update. The timestamp is:
    - Updated after each successful coordinator refresh
    - Persisted to storage via a post-update hook
    - Available for subclasses to calculate delta times between updates

    Subclasses should:
    1. Call super().__init__() to initialize timestamp tracking
    2. Implement _get_store() to provide the storage backend
    3. Implement _get_stored_state() and _save_state_with_timestamp() for persistence
    4. Use last_update_time property to access the last successful update timestamp
    """

    def __init__(self, hass: HomeAssistant, *args: Any, **kwargs: Any) -> None:
        """Initialize the timestamp coordinator."""
        super().__init__(hass, *args, **kwargs)
        self._last_update_time: datetime | None = None

    @property
    def last_update_time(self) -> datetime | None:
        """Return the timestamp of the last successful update."""
        return self._last_update_time

    def _async_refresh_finished(self) -> None:
        """
        Handle when a refresh has finished - update timestamp and persist state.

        This hook is called after a successful coordinator refresh but before
        listeners are notified. We use it to:
        1. Update the last successful update timestamp
        2. Trigger state persistence (including the new timestamp)
        """
        # Call parent hook first
        super()._async_refresh_finished()

        # Only update timestamp if the update was successful
        if self.last_update_success:
            self._last_update_time = datetime.now(UTC)

            # Trigger state persistence asynchronously
            # Subclasses should implement this to save state including timestamp
            self.hass.async_create_task(self._async_post_update_save())

    async def _async_post_update_save(self) -> None:
        """
        Save state after successful update.

        Subclasses should override this to persist their state including
        the last_update_time. This is called automatically after each
        successful coordinator refresh.
        """
        # Default implementation does nothing
        # Subclasses can override to save their state

    async def restore_last_update_time(self, stored_data: dict[str, Any]) -> None:
        """
        Restore last update timestamp from stored data.

        Args:
            stored_data: Dictionary containing stored state data

        """
        if stored_data and "last_update_time" in stored_data:
            try:
                self._last_update_time = datetime.fromisoformat(
                    stored_data["last_update_time"]
                )
            except (ValueError, TypeError):
                # Invalid timestamp format, start fresh
                self._last_update_time = None

    def get_time_since_last_update(self, now: datetime) -> float:
        """
        Calculate seconds since last update.

        Args:
            now: Current timestamp

        Returns:
            Seconds since last update, or a default interval if no previous update

        """
        if self._last_update_time is not None:
            return (now - self._last_update_time).total_seconds()
        # Return default update interval if no previous update
        if self.update_interval:
            return self.update_interval.total_seconds()
        # Fallback to 0 if no interval configured
        return 0.0
