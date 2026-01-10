"""
Custom integration to integrate Underfloor Heating Controller with Home Assistant.

For more details about this integration, please refer to
https://github.com/lnagel/hass-ufh-controller
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from slugify import slugify

from .const import (
    DEFAULT_TIMING,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
)
from .coordinator import UFHControllerDataUpdateCoordinator
from .data import UFHControllerData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import UFHControllerConfigEntry

CONTROLLER_SUBENTRY_UNIQUE_ID = "controller"

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> bool:
    """Set up Underfloor Heating Controller from a config entry."""
    LOGGER.debug("Setting up Underfloor Heating Controller entry: %s", entry.entry_id)

    # Ensure controller subentry exists (auto-create if missing)
    await _async_ensure_controller_subentry(hass, entry)

    # Check for and migrate any zone ID mismatches (happens when subentry is renamed)
    await _async_migrate_renamed_zones(hass, entry)

    coordinator = UFHControllerDataUpdateCoordinator(hass=hass, entry=entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = UFHControllerData(coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Listen for subentry updates and reload when zone subentries change
    # Note: Zone ID migration is handled during entry setup, not here,
    # because the reload happens before events are processed
    async def _async_handle_subentry_update(event: Any) -> None:
        """Handle subentry update event."""
        if event.data.get("entry_id") != entry.entry_id:
            return
        subentry_type = event.data.get("subentry_type")
        if subentry_type == SUBENTRY_TYPE_ZONE:
            LOGGER.debug("Zone subentry updated, scheduling reload")
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen("config_subentry_updated", _async_handle_subentry_update)
    )

    return True


async def _async_ensure_controller_subentry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> None:
    """Ensure the controller subentry exists, creating it if needed."""
    # Check if controller subentry already exists
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
            LOGGER.debug("Controller subentry already exists: %s", subentry.subentry_id)
            return

    # Create controller subentry with timing data
    # Try to migrate timing from options if available, otherwise use defaults
    timing = entry.options.get("timing", DEFAULT_TIMING)
    controller_name = entry.data.get("name", "Underfloor Heating Controller")
    controller_subentry = ConfigSubentry(
        data=MappingProxyType({"timing": timing}),
        subentry_type=SUBENTRY_TYPE_CONTROLLER,
        title=controller_name,
        unique_id=CONTROLLER_SUBENTRY_UNIQUE_ID,
    )

    hass.config_entries.async_add_subentry(entry, controller_subentry)
    LOGGER.debug("Created controller subentry for: %s", controller_name)


async def _async_migrate_renamed_zones(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> None:
    """
    Check all zone subentries and migrate zone IDs if any were renamed.

    This is called during entry setup to handle the case where a zone
    subentry was renamed (via HA's native rename action) and the zone ID
    needs to be updated to match the new name.

    We detect a rename by comparing subentry.title with subentry.data["name"].
    When a zone is created, both are the same. When renamed via HA's native
    rename action, only the title changes.
    """
    # Collect all zones that need migration
    # We collect first to avoid modifying subentries while iterating
    zones_to_migrate: list[tuple[ConfigSubentry, str, str]] = []

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_ZONE:
            continue

        # Check if the zone was renamed by comparing title with stored name
        stored_name = subentry.data.get("name", "")
        if subentry.title == stored_name:
            # Title matches stored name - no rename occurred
            continue

        old_zone_id = subentry.data.get("id", "")
        new_zone_id = slugify(subentry.title)

        # Check for conflicts
        conflict = False
        for other_subentry in entry.subentries.values():
            if other_subentry.subentry_id == subentry.subentry_id:
                continue
            if other_subentry.data.get("id") == new_zone_id:
                LOGGER.warning(
                    "Cannot rename zone '%s' to '%s': zone ID '%s' already exists",
                    old_zone_id,
                    subentry.title,
                    new_zone_id,
                )
                conflict = True
                break

        if not conflict:
            zones_to_migrate.append((subentry, old_zone_id, new_zone_id))

    # Perform migrations
    for subentry, old_zone_id, new_zone_id in zones_to_migrate:
        await _async_migrate_zone_id(hass, entry, subentry, old_zone_id, new_zone_id)
        await _async_migrate_stored_state(hass, entry, old_zone_id, new_zone_id)


async def _async_migrate_zone_id(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    subentry: ConfigSubentry,
    old_zone_id: str,
    new_zone_id: str,
) -> None:
    """
    Migrate a zone ID and all its references when a zone subentry is renamed.

    This updates:
    - Entity registry entries (unique_id contains zone_id)
    - Device registry entries (identifier contains zone_id)
    - Subentry data (data["id"] field)
    """
    controller_id = entry.data.get("controller_id", "")
    entry_id = entry.entry_id

    LOGGER.info(
        "Migrating zone ID from '%s' to '%s' for zone '%s'",
        old_zone_id,
        new_zone_id,
        subentry.title,
    )

    # Update entity registry entries
    entity_reg = er.async_get(hass)
    old_unique_id_prefix = f"{controller_id}_{old_zone_id}_"
    new_unique_id_prefix = f"{controller_id}_{new_zone_id}_"

    entities_to_update: list[tuple[str, str]] = []
    # Find entities by config entry and filter by unique_id prefix
    for entity_entry in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if (
            entity_entry.config_subentry_id == subentry.subentry_id
            and entity_entry.unique_id.startswith(old_unique_id_prefix)
        ):
            new_unique_id = entity_entry.unique_id.replace(
                old_unique_id_prefix, new_unique_id_prefix, 1
            )
            entities_to_update.append((entity_entry.entity_id, new_unique_id))

    for entity_id, new_unique_id in entities_to_update:
        entity_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)
        LOGGER.debug("Updated entity %s unique_id to %s", entity_id, new_unique_id)

    # Update device registry entry
    device_reg = dr.async_get(hass)
    old_device_identifier = (DOMAIN, f"{entry_id}_{old_zone_id}")
    new_device_identifier = (DOMAIN, f"{entry_id}_{new_zone_id}")

    device_entry = device_reg.async_get_device(identifiers={old_device_identifier})
    if device_entry:
        device_reg.async_update_device(
            device_entry.id,
            new_identifiers={new_device_identifier},
        )
        LOGGER.debug(
            "Updated device %s identifier from %s to %s",
            device_entry.id,
            old_device_identifier,
            new_device_identifier,
        )

    # Update the subentry data with the new zone_id
    new_data = {**subentry.data, "id": new_zone_id, "name": subentry.title}
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data=new_data,
    )
    LOGGER.debug("Updated subentry data with new zone_id: %s", new_zone_id)


async def _async_migrate_stored_state(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    old_zone_id: str,
    new_zone_id: str,
) -> None:
    """Migrate stored state data from old zone ID to new zone ID."""
    # Import here to avoid circular imports
    from homeassistant.helpers.storage import Store  # noqa: PLC0415

    from .coordinator import STORAGE_KEY, STORAGE_VERSION  # noqa: PLC0415

    store: Store[dict[str, Any]] = Store(
        hass,
        STORAGE_VERSION,
        f"{STORAGE_KEY}.{entry.entry_id}",
    )

    stored_data = await store.async_load()
    if stored_data is None:
        return

    zones_data = stored_data.get("zones", {})
    if old_zone_id not in zones_data:
        return

    # Migrate the zone data to the new key
    zones_data[new_zone_id] = zones_data.pop(old_zone_id)
    stored_data["zones"] = zones_data

    await store.async_save(stored_data)
    LOGGER.debug(
        "Migrated stored state from zone '%s' to '%s'",
        old_zone_id,
        new_zone_id,
    )


async def async_unload_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    LOGGER.debug("Unloading Underfloor Heating Controller entry: %s", entry.entry_id)

    # Save state before unloading
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_save_state()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Handle device removal request."""
    LOGGER.debug(
        "async_remove_config_entry_device called for device: %s, identifiers: %s",
        device_entry.id,
        device_entry.identifiers,
    )

    # Find the device identifier for our domain
    device_id = None
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            device_id = identifier[1]
            break

    if device_id is None:
        LOGGER.debug("No identifier found for domain %s", DOMAIN)
        return False

    # The controller device has identifier = entry_id
    # Zone devices have identifier = entry_id + "_" + zone_id
    if device_id == entry.entry_id:
        # Cannot delete the main controller device
        LOGGER.debug("Cannot delete main controller device")
        msg = "Cannot delete the controller. To remove it, delete the integration."
        raise HomeAssistantError(msg)

    # Zone devices are managed through subentries - deletion is handled by HA
    # when the subentry is deleted. Allow orphan device cleanup.
    LOGGER.debug("Allowing device removal for: %s", device_id)
    return True


__all__ = [
    "DOMAIN",
    "async_setup_entry",
    "async_unload_entry",
]
