"""Tests for synchronization manager."""

import json
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from werender.network.sync import SyncManager


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config_file = tmp_path / "werender.json"
    config_data = {"render_quality": "high", "output_format": "PNG"}
    config_file.write_text(json.dumps(config_data))
    return config_file


@pytest.fixture
def temp_addons_dir(tmp_path):
    """Create a temporary addons directory with some zip files."""
    addons_dir = tmp_path / "addons"
    addons_dir.mkdir()

    # Create some fake addon zip files
    addon1 = addons_dir / "addon1.zip"
    addon2 = addons_dir / "addon2.zip"

    with zipfile.ZipFile(addon1, "w") as zf:
        zf.writestr("addon1/__init__.py", "# Addon 1")

    with zipfile.ZipFile(addon2, "w") as zf:
        zf.writestr("addon2/__init__.py", "# Addon 2")

    return addons_dir


class TestSyncManagerInit:
    """Tests for SyncManager initialization."""

    def test_init_with_paths(self, tmp_path):
        """Test initialization with config and addons paths."""
        config_path = tmp_path / "config.json"
        addons_dir = tmp_path / "addons"

        manager = SyncManager(config_path=config_path, addons_dir=addons_dir)

        assert manager.config_path == config_path
        assert manager.addons_dir == addons_dir
        assert manager.cached_manifest is None

    def test_init_without_paths(self):
        """Test initialization without paths."""
        manager = SyncManager()

        assert manager.config_path is None
        assert manager.addons_dir is None
        assert manager.cached_manifest is None


class TestGetManifest:
    """Tests for get_manifest method."""

    def test_get_manifest_with_no_paths(self):
        """Test getting manifest when no paths are configured."""
        manager = SyncManager()

        manifest = manager.get_manifest()

        assert manifest["settings_hash"] == ""
        assert manifest["addons_hash"] == ""
        assert manifest["timestamp"] == 0

    def test_get_manifest_with_config_only(self, temp_config_file):
        """Test getting manifest with only config file."""
        manager = SyncManager(config_path=temp_config_file)

        manifest = manager.get_manifest()

        assert manifest["settings_hash"] != ""
        assert manifest["addons_hash"] == ""
        assert manifest["timestamp"] == 0

    def test_get_manifest_with_addons_only(self, temp_addons_dir):
        """Test getting manifest with only addons directory."""
        manager = SyncManager(addons_dir=temp_addons_dir)

        manifest = manager.get_manifest()

        assert manifest["settings_hash"] == ""
        assert manifest["addons_hash"] != ""
        assert manifest["timestamp"] == 0

    def test_get_manifest_with_both(self, temp_config_file, temp_addons_dir):
        """Test getting manifest with both config and addons."""
        manager = SyncManager(
            config_path=temp_config_file, addons_dir=temp_addons_dir
        )

        manifest = manager.get_manifest()

        assert manifest["settings_hash"] != ""
        assert manifest["addons_hash"] != ""
        assert manifest["timestamp"] == 0

    def test_get_manifest_deterministic(self, temp_config_file, temp_addons_dir):
        """Test that manifest is deterministic (same inputs = same output)."""
        manager = SyncManager(
            config_path=temp_config_file, addons_dir=temp_addons_dir
        )

        manifest1 = manager.get_manifest()
        manifest2 = manager.get_manifest()

        assert manifest1 == manifest2


class TestGetAddonsList:
    """Tests for get_addons_list method."""

    def test_get_addons_list_no_directory(self):
        """Test getting addons list when no directory is configured."""
        manager = SyncManager()

        addons = manager.get_addons_list()

        assert addons == []

    def test_get_addons_list_directory_not_exists(self, tmp_path):
        """Test getting addons list when directory doesn't exist."""
        manager = SyncManager(addons_dir=tmp_path / "nonexistent")

        addons = manager.get_addons_list()

        assert addons == []

    def test_get_addons_list_empty_directory(self, tmp_path):
        """Test getting addons list from empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        manager = SyncManager(addons_dir=empty_dir)

        addons = manager.get_addons_list()

        assert addons == []

    def test_get_addons_list_with_addons(self, temp_addons_dir):
        """Test getting addons list with actual addon files."""
        manager = SyncManager(addons_dir=temp_addons_dir)

        addons = manager.get_addons_list()

        assert len(addons) == 2
        assert any(a["name"] == "addon1" for a in addons)
        assert any(a["name"] == "addon2" for a in addons)

        # Check structure
        for addon in addons:
            assert "name" in addon
            assert "filename" in addon
            assert "hash" in addon
            assert "size" in addon
            assert addon["size"] > 0

    def test_get_addons_list_ignores_non_zip(self, tmp_path):
        """Test that get_addons_list ignores non-zip files."""
        addons_dir = tmp_path / "addons"
        addons_dir.mkdir()

        # Create zip and non-zip files
        (addons_dir / "addon.zip").touch()
        (addons_dir / "readme.txt").touch()
        (addons_dir / "script.py").touch()
        subfolder = addons_dir / "subfolder"
        subfolder.mkdir()

        manager = SyncManager(addons_dir=addons_dir)

        addons = manager.get_addons_list()

        assert len(addons) == 1
        assert addons[0]["name"] == "addon"


class TestGetSettings:
    """Tests for get_settings method."""

    def test_get_settings_no_config(self):
        """Test getting settings when no config is configured."""
        manager = SyncManager()

        settings = manager.get_settings()

        assert settings == {}

    def test_get_settings_file_not_exists(self, tmp_path):
        """Test getting settings when config file doesn't exist."""
        manager = SyncManager(config_path=tmp_path / "nonexistent.json")

        settings = manager.get_settings()

        assert settings == {}

    def test_get_settings_valid_json(self, temp_config_file):
        """Test getting settings from valid JSON file."""
        manager = SyncManager(config_path=temp_config_file)

        settings = manager.get_settings()

        assert settings == {"render_quality": "high", "output_format": "PNG"}

    def test_get_settings_invalid_json(self, tmp_path):
        """Test getting settings from invalid JSON file."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{ invalid json }")

        manager = SyncManager(config_path=invalid_file)

        settings = manager.get_settings()

        assert settings == {}


class TestCalculateFileHash:
    """Tests for _calculate_file_hash method."""

    def test_calculate_hash_regular_file(self, tmp_path):
        """Test calculating hash of a regular file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        manager = SyncManager()

        hash1 = manager._calculate_file_hash(test_file)
        hash2 = manager._calculate_file_hash(test_file)

        assert hash1 == hash2
        assert len(hash1) == 32  # MD5 hash length

    def test_calculate_hash_different_files(self, tmp_path):
        """Test that different files have different hashes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        file1.write_text("content1")
        file2.write_text("content2")

        manager = SyncManager()

        hash1 = manager._calculate_file_hash(file1)
        hash2 = manager._calculate_file_hash(file2)

        assert hash1 != hash2

    def test_calculate_hash_nonexistent_file(self, tmp_path):
        """Test calculating hash of non-existent file."""
        manager = SyncManager()

        hash_value = manager._calculate_file_hash(tmp_path / "nonexistent.txt")

        assert hash_value == ""


class TestPackageAddon:
    """Tests for package_addon method."""

    def test_package_addon_folder(self, tmp_path):
        """Test packaging an addon folder."""
        # Create addon folder structure
        addon_dir = tmp_path / "test_addon"
        addon_dir.mkdir()
        (addon_dir / "__init__.py").write_text("# Test addon")
        (addon_dir / "main.py").write_text("print('hello')")

        output_dir = tmp_path / "output"

        manager = SyncManager()

        result = manager.package_addon(addon_dir, output_dir)

        assert result is not None
        assert result.name == "test_addon.zip"
        assert result.exists()

        # Verify zip contents
        with zipfile.ZipFile(result, "r") as zf:
            names = zf.namelist()
            assert "test_addon/__init__.py" in names
            assert "test_addon/main.py" in names

    def test_package_addon_file(self, tmp_path):
        """Test packaging a single file as addon."""
        addon_file = tmp_path / "single_file.py"
        addon_file.write_text("# Single file addon")

        output_dir = tmp_path / "output"

        manager = SyncManager()

        result = manager.package_addon(addon_file, output_dir)

        assert result is not None
        assert result.name == "single_file.py.zip"
        assert result.exists()

    def test_package_addon_nonexistent(self, tmp_path):
        """Test packaging non-existent addon."""
        output_dir = tmp_path / "output"

        manager = SyncManager()

        result = manager.package_addon(tmp_path / "nonexistent", output_dir)

        assert result is None

    def test_package_addon_creates_output_dir(self, tmp_path):
        """Test that package_addon creates output directory if needed."""
        addon_dir = tmp_path / "test_addon"
        addon_dir.mkdir()
        (addon_dir / "__init__.py").write_text("# Test")

        output_dir = tmp_path / "nested" / "output" / "dir"

        manager = SyncManager()

        result = manager.package_addon(addon_dir, output_dir)

        assert result is not None
        assert output_dir.exists()

    def test_package_addon_excludes_pycache(self, tmp_path):
        """Test that package_addon excludes __pycache__ directories."""
        addon_dir = tmp_path / "test_addon"
        addon_dir.mkdir()
        (addon_dir / "__init__.py").write_text("# Test")
        pycache = addon_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-310.pyc").write_bytes(b"compiled")

        output_dir = tmp_path / "output"

        manager = SyncManager()

        result = manager.package_addon(addon_dir, output_dir)

        assert result is not None
        with zipfile.ZipFile(result, "r") as zf:
            assert "__pycache__" not in [n.split("/")[0] for n in zf.namelist()]

    def test_package_addon_excludes_git(self, tmp_path):
        """Test that package_addon excludes .git directories."""
        addon_dir = tmp_path / "test_addon"
        addon_dir.mkdir()
        (addon_dir / "__init__.py").write_text("# Test")
        git_dir = addon_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")

        output_dir = tmp_path / "output"

        manager = SyncManager()

        result = manager.package_addon(addon_dir, output_dir)

        assert result is not None
        with zipfile.ZipFile(result, "r") as zf:
            assert ".git" not in [n.split("/")[0] for n in zf.namelist()]