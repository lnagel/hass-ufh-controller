"""Test Underfloor Heating Controller setup and unload."""

from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    SUBENTRY_TYPE_ZONE,
)


async def test_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test successful setup of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data is not None
    assert mock_config_entry.runtime_data.coordinator is not None


async def test_setup_entry_no_zones(
    hass: HomeAssistant,
    mock_config_entry_no_zones: MockConfigEntry,
) -> None:
    """Test setup with no zones configured."""
    mock_config_entry_no_zones.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry_no_zones.entry_id)
    await hass.async_block_till_done()


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test successful unload of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_reload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reload of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Reload the entry
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


# =============================================================================
# Zone ID Rename Tests
# =============================================================================


def _create_zone_config_entry(
    controller_id: str = "test_controller",
    zone_id: str = "living_room",
    zone_name: str = "Living Room",
    entry_id: str = "test_entry_zone_rename",
) -> MockConfigEntry:
    """Create a config entry with a zone for rename testing."""
    zone_data: dict[str, Any] = {
        "id": zone_id,
        "name": zone_name,
        "circuit_type": "regular",
        "temp_sensor": "sensor.living_room_temp",
        "valve_switch": "switch.living_room_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
        "presets": {
            "home": 21.0,
            "away": 16.0,
        },
    }

    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": controller_id,
        },
        options={"timing": DEFAULT_TIMING},
        entry_id=entry_id,
        unique_id=controller_id,
        subentries_data=[
            {
                "data": zone_data,
                "subentry_id": "subentry_living_room",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": zone_name,
                "unique_id": zone_id,
            }
        ],
    )


async def test_zone_rename_updates_zone_id(
    hass: HomeAssistant,
) -> None:
    """Test that renaming a zone subentry updates the zone ID in subentry data."""
    config_entry = _create_zone_config_entry()
    config_entry.add_to_hass(hass)

    # Set up temperature sensor for entity availability
    hass.states.async_set("sensor.living_room_temp", "20.5")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the subentry
    subentry = next(iter(config_entry.subentries.values()))
    assert subentry.data["id"] == "living_room"

    # Simulate a rename by updating the subentry title (this is what HA's rename does)
    hass.config_entries.async_update_subentry(
        config_entry,
        subentry,
        title="Main Living Room",
    )
    await hass.async_block_till_done()

    # Verify the zone ID was updated
    # slugify uses "-" as separator: "Main Living Room" -> "main-living-room"
    updated_subentry = config_entry.subentries.get(subentry.subentry_id)
    assert updated_subentry is not None
    assert updated_subentry.data["id"] == "main-living-room"
    assert updated_subentry.data["name"] == "Main Living Room"


async def test_zone_rename_updates_entity_unique_ids(
    hass: HomeAssistant,
) -> None:
    """Test that renaming a zone updates entity registry unique_ids."""
    config_entry = _create_zone_config_entry(
        controller_id="test_controller_entity_rename"
    )
    config_entry.add_to_hass(hass)

    # Set up temperature sensor for entity availability
    hass.states.async_set("sensor.living_room_temp", "20.5")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get entity registry and verify initial unique_ids
    entity_reg = er.async_get(hass)
    climate_entity = entity_reg.async_get("climate.living_room_climate")
    assert climate_entity is not None
    assert (
        climate_entity.unique_id == "test_controller_entity_rename_living_room_climate"
    )

    # Get the subentry
    subentry = next(iter(config_entry.subentries.values()))

    # Simulate a rename
    hass.config_entries.async_update_subentry(
        config_entry,
        subentry,
        title="Master Bedroom",
    )
    await hass.async_block_till_done()

    # Verify the entity unique_id was updated
    # Note: slugify uses "-" as separator, so "Master Bedroom" becomes "master-bedroom"
    climate_entity = entity_reg.async_get("climate.living_room_climate")
    assert climate_entity is not None
    assert (
        climate_entity.unique_id
        == "test_controller_entity_rename_master-bedroom_climate"
    )


async def test_zone_rename_updates_device_identifier(
    hass: HomeAssistant,
) -> None:
    """Test that renaming a zone updates device registry identifier."""
    entry_id = "test_entry_device_rename"
    config_entry = _create_zone_config_entry(
        controller_id="test_controller_device_rename",
        entry_id=entry_id,
    )
    config_entry.add_to_hass(hass)

    # Set up temperature sensor for entity availability
    hass.states.async_set("sensor.living_room_temp", "20.5")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get device registry and verify initial identifier
    device_reg = dr.async_get(hass)
    old_identifier = (DOMAIN, f"{entry_id}_living_room")
    device = device_reg.async_get_device(identifiers={old_identifier})
    assert device is not None

    # Get the subentry
    subentry = next(iter(config_entry.subentries.values()))

    # Simulate a rename
    hass.config_entries.async_update_subentry(
        config_entry,
        subentry,
        title="Kitchen",
    )
    await hass.async_block_till_done()

    # Verify the device identifier was updated
    # Note: The zone_id is now "kitchen" (same slug as "Kitchen")
    new_identifier = (DOMAIN, f"{entry_id}_kitchen")
    device = device_reg.async_get_device(identifiers={new_identifier})
    assert device is not None

    # Old identifier should no longer exist
    old_device = device_reg.async_get_device(identifiers={old_identifier})
    assert old_device is None


async def test_zone_rename_migrates_stored_state(
    hass: HomeAssistant,
) -> None:
    """Test that renaming a zone migrates stored state data."""
    config_entry = _create_zone_config_entry(
        controller_id="test_controller_state_migrate"
    )

    # Pre-existing stored state with old zone_id
    stored_data = {
        "version": 1,
        "controller_mode": "auto",
        "zones": {
            "living_room": {
                "integral": 45.5,
                "last_error": 0.5,
                "setpoint": 22.0,
                "enabled": True,
            },
        },
    }

    saved_data: dict[str, Any] = {}

    async def capture_save(data: dict) -> None:
        nonlocal saved_data
        saved_data = data

    with (
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=stored_data,
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_save",
            side_effect=capture_save,
        ),
    ):
        config_entry.add_to_hass(hass)
        hass.states.async_set("sensor.living_room_temp", "20.5")

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Get the subentry
        subentry = next(iter(config_entry.subentries.values()))

        # Simulate a rename
        hass.config_entries.async_update_subentry(
            config_entry,
            subentry,
            title="Office",
        )
        await hass.async_block_till_done()

    # The stored state should have been migrated to the new key
    # Note: The zone_id is now "office" (same slug as "Office")
    assert "zones" in saved_data
    assert "office" in saved_data["zones"]
    assert "living_room" not in saved_data["zones"]
    # The integral value was preserved during migration
    # (may have been slightly updated by PID controller during refresh)
    assert saved_data["zones"]["office"]["integral"] >= 45.5


async def test_zone_rename_conflict_prevents_migration(
    hass: HomeAssistant,
) -> None:
    """Test that renaming to a conflicting zone ID is prevented."""
    # Create entry with two zones
    # Use zone IDs that match the slugified zone names (with dashes)
    zone1_data: dict[str, Any] = {
        "id": "zone-1",
        "name": "Zone 1",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone1_temp",
        "valve_switch": "switch.zone1_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
        "presets": {},
    }
    zone2_data: dict[str, Any] = {
        "id": "zone-2",
        "name": "Zone 2",
        "circuit_type": "regular",
        "temp_sensor": "sensor.zone2_temp",
        "valve_switch": "switch.zone2_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
        "presets": {},
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={
            "name": "Test Controller",
            "controller_id": "test_controller_conflict",
        },
        options={"timing": DEFAULT_TIMING},
        entry_id="test_entry_conflict",
        unique_id="test_controller_conflict",
        subentries_data=[
            {
                "data": zone1_data,
                "subentry_id": "subentry_zone1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Zone 1",
                "unique_id": "zone-1",
            },
            {
                "data": zone2_data,
                "subentry_id": "subentry_zone2",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "Zone 2",
                "unique_id": "zone-2",
            },
        ],
    )

    config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.zone1_temp", "20.5")
    hass.states.async_set("sensor.zone2_temp", "21.0")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get subentry for zone1
    subentry_zone1 = config_entry.subentries.get("subentry_zone1")
    assert subentry_zone1 is not None
    assert subentry_zone1.data["id"] == "zone-1"

    # Try to rename zone1 to "Zone 2" which would conflict with zone2's ID
    # Note: slugify("Zone 2") = "zone-2", which conflicts with existing zone-2
    hass.config_entries.async_update_subentry(
        config_entry,
        subentry_zone1,
        title="Zone 2",
    )
    await hass.async_block_till_done()

    # The zone ID should NOT have been updated due to conflict
    updated_subentry = config_entry.subentries.get("subentry_zone1")
    assert updated_subentry is not None
    assert updated_subentry.data["id"] == "zone-1"  # Should remain unchanged


async def test_zone_rename_no_change_when_same_slug(
    hass: HomeAssistant,
) -> None:
    """Test that no migration occurs when the slugified name is the same."""
    # Use zone_id that matches slugified zone_name (slugify uses dashes)
    # slugify("Living Room") = "living-room"
    config_entry = _create_zone_config_entry(
        controller_id="test_controller_same_slug",
        zone_id="living-room",
        zone_name="Living Room",
    )
    config_entry.add_to_hass(hass)
    hass.states.async_set("sensor.living_room_temp", "20.5")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the subentry
    subentry = next(iter(config_entry.subentries.values()))

    # Update the title to something that slugifies to the same value
    # "Living Room" and "LIVING ROOM" both slugify to "living-room"
    hass.config_entries.async_update_subentry(
        config_entry,
        subentry,
        title="LIVING ROOM",
    )
    await hass.async_block_till_done()

    # The zone ID should remain unchanged (slug is the same)
    updated_subentry = config_entry.subentries.get(subentry.subentry_id)
    assert updated_subentry is not None
    assert updated_subentry.data["id"] == "living-room"
