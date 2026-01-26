"""Test const module."""

import json

from custom_components.ufh_controller.const import MANIFEST_PATH, VERSION


class TestVersion:
    """Test cases for VERSION constant."""

    def test_manifest_path_exists(self) -> None:
        """MANIFEST_PATH should point to an existing file."""
        assert MANIFEST_PATH.exists()

    def test_version_matches_manifest(self) -> None:
        """VERSION should match the version in manifest.json."""
        manifest = json.loads(MANIFEST_PATH.read_text())
        assert manifest["version"] == VERSION

    def test_version_is_string(self) -> None:
        """VERSION should be a string."""
        assert isinstance(VERSION, str)
