"""Unit tests for storage migration."""

from custom_components.ufh_controller.coordinator import UFHControllerStore


class TestMigrateV1ToV2:
    """Test V1 to V2 storage migration."""

    def test_controller_keys_migrated(self) -> None:
        """Test controller_mode and flush_enabled are nested under controller."""
        v1_data = {"controller_mode": "heat", "flush_enabled": True, "zones": {}}
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)

        assert v2_data["controller"]["mode"] == "heat"
        assert v2_data["controller"]["flush_enabled"] is True

    def test_controller_defaults_when_missing(self) -> None:
        """Test controller defaults when keys are missing in V1."""
        v1_data = {"zones": {}}
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)

        assert v2_data["controller"]["mode"] is None
        assert v2_data["controller"]["flush_enabled"] is False

    def test_pid_keys_renamed(self) -> None:
        """Test PID keys are renamed from V1 to V2."""
        v1_data = {
            "zones": {
                "zone1": {
                    "error": 1.5,
                    "p_term": 50.0,
                    "i_term": 25.0,
                    "d_term": 0.5,
                    "duty_cycle": 75.0,
                }
            }
        }
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)
        zone = v2_data["zones"]["zone1"]

        assert zone["pid_error"] == 1.5
        assert zone["pid_proportional"] == 50.0
        assert zone["pid_integral"] == 25.0
        assert zone["pid_derivative"] == 0.5
        assert zone["duty_cycle"] == 75.0
        assert "error" not in zone
        assert "p_term" not in zone
        assert "i_term" not in zone
        assert "d_term" not in zone

    def test_temperature_key_renamed(self) -> None:
        """Test V1 'temperature' becomes V2 'current'."""
        v1_data = {"zones": {"zone1": {"temperature": 20.5, "display_temp": 20.3}}}
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)
        zone = v2_data["zones"]["zone1"]

        assert zone["current"] == 20.5
        assert zone["display_temp"] == 20.3
        assert "temperature" not in zone

    def test_timestamps_preserved(self) -> None:
        """Test timestamps are passed through."""
        v1_data = {
            "zones": {},
            "last_update_success_time": "2026-01-01T12:00:00+00:00",
            "last_force_update": "2026-01-01T12:00:00+00:00",
        }
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)

        assert v2_data["last_update_success_time"] == "2026-01-01T12:00:00+00:00"
        assert v2_data["last_force_update"] == "2026-01-01T12:00:00+00:00"

    def test_none_values_filtered_from_zones(self) -> None:
        """Test that None values are filtered out from zone data."""
        v1_data = {
            "zones": {
                "zone1": {
                    "setpoint": 21.0,
                    "enabled": True,
                    # These V1 keys don't exist, so will be None after migration
                }
            }
        }
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)
        zone = v2_data["zones"]["zone1"]

        assert zone["setpoint"] == 21.0
        assert zone["enabled"] is True
        # None values should not be present
        assert "pid_error" not in zone
        assert "current" not in zone

    def test_all_zone_fields_migrated(self) -> None:
        """Test complete zone data migration with all fields."""
        v1_data = {
            "zones": {
                "zone1": {
                    "setpoint": 21.5,
                    "enabled": True,
                    "preset_mode": "away",
                    "used_duration": 1800.0,
                    "error": 0.5,
                    "p_term": 10.0,
                    "i_term": 5.0,
                    "d_term": 0.1,
                    "duty_cycle": 50.0,
                    "temperature": 21.0,
                    "display_temp": 21.0,
                }
            }
        }
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)
        zone = v2_data["zones"]["zone1"]

        assert zone["setpoint"] == 21.5
        assert zone["enabled"] is True
        assert zone["preset_mode"] == "away"
        assert zone["used_duration"] == 1800.0
        assert zone["pid_error"] == 0.5
        assert zone["pid_proportional"] == 10.0
        assert zone["pid_integral"] == 5.0
        assert zone["pid_derivative"] == 0.1
        assert zone["duty_cycle"] == 50.0
        assert zone["current"] == 21.0
        assert zone["display_temp"] == 21.0

    def test_multiple_zones_migrated(self) -> None:
        """Test migration handles multiple zones."""
        v1_data = {
            "zones": {
                "zone1": {"setpoint": 20.0, "temperature": 19.5},
                "zone2": {"setpoint": 22.0, "temperature": 21.5},
            }
        }
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)

        assert v2_data["zones"]["zone1"]["setpoint"] == 20.0
        assert v2_data["zones"]["zone1"]["current"] == 19.5
        assert v2_data["zones"]["zone2"]["setpoint"] == 22.0
        assert v2_data["zones"]["zone2"]["current"] == 21.5

    def test_empty_zones_dict(self) -> None:
        """Test migration handles empty zones dict."""
        v1_data = {"controller_mode": "off", "zones": {}}
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)

        assert v2_data["controller"]["mode"] == "off"
        assert v2_data["zones"] == {}

    def test_missing_zones_key(self) -> None:
        """Test migration handles missing zones key."""
        v1_data = {"controller_mode": "heat"}
        v2_data = UFHControllerStore._migrate_v1_to_v2(v1_data)

        assert v2_data["controller"]["mode"] == "heat"
        assert v2_data["zones"] == {}


class TestMigrateV2ToV3:
    """Test V2 to V3 storage migration."""

    def test_moves_last_force_update_to_controller(self) -> None:
        """Test last_force_update is moved from root to controller section."""
        v2_data = {
            "controller": {"mode": "heat", "flush_enabled": False},
            "zones": {},
            "last_force_update": "2026-01-01T12:00:00+00:00",
        }
        v3_data = UFHControllerStore._migrate_v2_to_v3(v2_data)

        assert "last_force_update" not in v3_data
        assert v3_data["controller"]["last_force_update"] == "2026-01-01T12:00:00+00:00"

    def test_no_last_force_update_is_noop(self) -> None:
        """Test migration is a no-op when last_force_update is absent."""
        v2_data = {
            "controller": {"mode": "heat"},
            "zones": {},
        }
        v3_data = UFHControllerStore._migrate_v2_to_v3(v2_data)

        assert "last_force_update" not in v3_data
        assert "last_force_update" not in v3_data["controller"]


class TestAsyncMigrateFunc:
    """Test the _async_migrate_func method."""

    async def test_v1_migrates_through_v2_to_v3(self) -> None:
        """Test that V1 data is migrated through V2 to V3."""
        store = UFHControllerStore.__new__(UFHControllerStore)
        v1_data = {
            "controller_mode": "heat",
            "zones": {},
            "last_force_update": "2026-01-01T12:00:00+00:00",
        }

        result = await store._async_migrate_func(1, 0, v1_data)

        assert result["controller"]["mode"] == "heat"
        # V1→V2 puts at root, V2→V3 moves to controller
        assert "last_force_update" not in result
        assert result["controller"]["last_force_update"] == "2026-01-01T12:00:00+00:00"

    async def test_v2_migrates_to_v3(self) -> None:
        """Test that V2 data triggers V2→V3 migration."""
        store = UFHControllerStore.__new__(UFHControllerStore)
        v2_data = {
            "controller": {"mode": "heat"},
            "zones": {},
            "last_force_update": "2026-01-01T12:00:00+00:00",
        }

        result = await store._async_migrate_func(2, 0, v2_data)

        assert "last_force_update" not in result
        assert result["controller"]["last_force_update"] == "2026-01-01T12:00:00+00:00"

    async def test_v3_data_unchanged(self) -> None:
        """Test that V3 data is returned unchanged."""
        store = UFHControllerStore.__new__(UFHControllerStore)
        v3_data = {
            "controller": {
                "mode": "heat",
                "last_force_update": "2026-01-01T12:00:00+00:00",
            },
            "zones": {},
        }

        result = await store._async_migrate_func(3, 0, v3_data)

        assert result is v3_data

    async def test_future_versions_unchanged(self) -> None:
        """Test that future versions are returned unchanged."""
        store = UFHControllerStore.__new__(UFHControllerStore)
        future_data = {"controller": {"mode": "heat"}, "zones": {}, "new_field": True}

        result = await store._async_migrate_func(4, 0, future_data)

        assert result is future_data
