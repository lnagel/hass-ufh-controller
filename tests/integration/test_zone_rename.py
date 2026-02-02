"""Tests for zone ID migration when subentries are renamed."""

from typing import Any

import pytest
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


def _zone_data(zone_id: str, name: str, sensor_prefix: str) -> dict[str, Any]:
    """Create zone data with given id and name."""
    return {
        "id": zone_id,
        "name": name,
        "circuit_type": "regular",
        "temp_sensor": f"sensor.{sensor_prefix}_temp",
        "valve_switch": f"switch.{sensor_prefix}_valve",
        "setpoint": DEFAULT_SETPOINT,
        "pid": DEFAULT_PID,
        "window_sensors": [],
    }


@pytest.fixture
def mock_renamed_zone_entry() -> MockConfigEntry:
    """Config entry where subentry title differs from data name (simulates rename)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={"name": "Test Controller", "controller_id": "ctrl"},
        options={"timing": DEFAULT_TIMING},
        entry_id="entry_rename",
        unique_id="ctrl_rename",
        subentries_data=[
            {
                "data": _zone_data("old-zone", "Old Zone", "zone1"),
                "subentry_id": "sub1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "New Zone",  # Renamed title (differs from data["name"])
                "unique_id": "old-zone",
            }
        ],
    )


async def test_zone_rename_migrates_existing_entities(
    hass: HomeAssistant,
    mock_renamed_zone_entry: MockConfigEntry,
) -> None:
    """Test zone ID migration updates existing entities and devices."""
    hass.states.async_set("sensor.zone1_temp", "20.0")
    hass.states.async_set("switch.zone1_valve", "off")

    mock_renamed_zone_entry.add_to_hass(hass)
    entry = mock_renamed_zone_entry
    subentry = next(iter(entry.subentries.values()))

    # Pre-register device and entity with OLD zone ID (simulates prior setup)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_old-zone")},
        name="Old Zone",
    )
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "climate",
        DOMAIN,
        "ctrl_old-zone_climate",
        config_entry=entry,
        config_subentry_id=subentry.subentry_id,
        device_id=device.id,
    )

    # Now set up entry - migration should update the pre-registered entities
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Verify subentry data was updated
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["id"] == "new-zone"

    # Verify device identifier was migrated
    assert dev_reg.async_get_device(identifiers={(DOMAIN, "entry_rename_new-zone")})

    # Verify entity unique_id was migrated (look up by unique_id, not entity_id)
    climate = ent_reg.async_get_entity_id("climate", DOMAIN, "ctrl_new-zone_climate")
    assert climate is not None


async def test_zone_rename_fresh_setup(
    hass: HomeAssistant,
    mock_renamed_zone_entry: MockConfigEntry,
) -> None:
    """Test zone ID migration on fresh setup (no pre-existing entities/devices)."""
    hass.states.async_set("sensor.zone1_temp", "20.0")
    hass.states.async_set("switch.zone1_valve", "off")

    mock_renamed_zone_entry.add_to_hass(hass)
    entry = mock_renamed_zone_entry
    subentry = next(iter(entry.subentries.values()))

    # Pre-register entity with same subentry but different unique_id prefix
    # This exercises the branch where entity exists but doesn't match the prefix
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        "different_prefix_sensor",  # Doesn't start with "ctrl_old-zone_"
        config_entry=entry,
        config_subentry_id=subentry.subentry_id,
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Subentry data should be updated with new zone ID
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["id"] == "new-zone"
    assert subentry.data["name"] == "New Zone"


async def test_zone_rename_skips_when_slug_unchanged(hass: HomeAssistant) -> None:
    """Test migration skips when title changes but slug remains the same."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data={"name": "Test Controller", "controller_id": "ctrl"},
        options={"timing": DEFAULT_TIMING},
        entry_id="entry_slug",
        unique_id="ctrl_slug",
        subentries_data=[
            {
                "data": _zone_data("my-zone", "My Zone", "zone1"),
                "subentry_id": "sub1",
                "subentry_type": SUBENTRY_TYPE_ZONE,
                "title": "My  Zone",  # Extra space - but slugifies to same "my-zone"
                "unique_id": "my-zone",
            }
        ],
    )
    hass.states.async_set("sensor.zone1_temp", "20.0")
    hass.states.async_set("switch.zone1_valve", "off")

    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Subentry data should NOT be updated since slug is unchanged
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["id"] == "my-zone"
    assert subentry.data["name"] == "My Zone"  # Original name preserved
