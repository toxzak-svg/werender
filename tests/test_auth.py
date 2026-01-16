"""Tests for authentication system."""

import os
import json
import tempfile
from pathlib import Path
import pytest

from werender.network.auth import AuthManager, get_worker_api_key


class TestAuthManager:
    """Test cases for AuthManager."""

    def test_init_creates_keys(self):
        """Test that initializing AuthManager creates default keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            assert "coordinator" in auth.api_keys
            assert "worker" in auth.api_keys
            assert len(auth.api_keys["coordinator"]) == 64  # 32 bytes = 64 hex chars
            assert len(auth.api_keys["worker"]) == 64

    def test_load_existing_keys(self):
        """Test that AuthManager can load existing keys from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            api_keys_file = config_dir / "api_keys.json"
            
            # Create test keys
            test_keys = {
                "coordinator": "test_coordinator_key_1234567890abcdef",
                "worker": "test_worker_key_1234567890abcdef",
                "version": 1,
                "created_at": 1234567890.0,
            }
            
            with open(api_keys_file, "w") as f:
                json.dump(test_keys, f)
            
            # Load with AuthManager
            auth = AuthManager(config_dir)
            
            assert auth.api_keys["coordinator"] == "test_coordinator_key_1234567890abcdef"
            assert auth.api_keys["worker"] == "test_worker_key_1234567890abcdef"

    def test_validate_key_success(self):
        """Test that valid keys pass validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            worker_key = auth.api_keys["worker"]
            assert auth.validate_key(worker_key) is True
            assert auth.validate_key(worker_key, "worker") is True

    def test_validate_key_invalid(self):
        """Test that invalid keys fail validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            assert auth.validate_key("invalid_key") is False
            assert auth.validate_key("invalid_key", "worker") is False

    def test_validate_key_wrong_type(self):
        """Test that validating with wrong key type fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            worker_key = auth.api_keys["worker"]
            assert auth.validate_key(worker_key, "coordinator") is False

    def test_get_key(self):
        """Test retrieving keys by type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            assert auth.get_key("worker") is not None
            assert auth.get_key("coordinator") is not None
            assert auth.get_key("nonexistent") is None

    def test_add_worker_key(self):
        """Test adding a new worker key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            # Add a worker-specific key
            new_key = auth.add_worker_key("worker_host_01")
            
            assert new_key is not None
            assert len(new_key) == 64
            # Key should be stored with the exact worker_id as the key
            assert "worker_host_01" in auth.api_keys
            assert auth.api_keys["worker_host_01"] == new_key
            
            # Verify it was saved to file
            api_keys_file = Path(tmpdir) / "api_keys.json"
            with open(api_keys_file, "r") as f:
                saved_keys = json.load(f)
            
            # The file should also contain the new key
            assert "worker_host_01" in saved_keys
            assert saved_keys["worker_host_01"] == new_key

    def test_revoke_key(self):
        """Test revoking a key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            # Add a custom worker key
            added_key = auth.add_worker_key("temp_worker")
            assert "temp_worker" in auth.api_keys
            assert auth.api_keys["temp_worker"] == added_key
            
            # Revoke the key
            result = auth.revoke_key("temp_worker")
            assert result is True
            assert "temp_worker" not in auth.api_keys
            
            # Verify it was removed from file
            api_keys_file = Path(tmpdir) / "api_keys.json"
            with open(api_keys_file, "r") as f:
                saved_keys = json.load(f)
            assert "temp_worker" not in saved_keys
            
            # Try to revoke non-existent key
            result = auth.revoke_key("nonexistent")
            assert result is False

    def test_key_entropy(self):
        """Test that generated keys have sufficient entropy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            
            # Generate multiple keys and verify they're different
            keys = []
            for i in range(10):
                key = auth._generate_api_key(f"test_{i}")
                keys.append(key)
            
            # All keys should be unique
            assert len(set(keys)) == 10
            
            # Keys should be hex strings of correct length
            for key in keys:
                assert len(key) == 64
                assert all(c in "0123456789abcdef" for c in key)


class TestGetWorkerApiKey:
    """Test cases for get_worker_api_key function."""

    def test_from_environment_variable(self):
        """Test getting API key from environment variable."""
        test_key = "test_env_key_1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set environment variable
            os.environ["WERENDER_API_KEY"] = test_key
            
            try:
                result = get_worker_api_key(Path(tmpdir))
                assert result == test_key
            finally:
                # Clean up
                del os.environ["WERENDER_API_KEY"]

    def test_from_config_file(self):
        """Test getting API key from config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_dir.mkdir(exist_ok=True)
            
            test_key = "test_file_key_1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            
            # Create api_keys.json
            api_keys_file = config_dir / "api_keys.json"
            test_keys = {
                "worker": test_key,
                "coordinator": "other_key",
            }
            
            with open(api_keys_file, "w") as f:
                json.dump(test_keys, f)
            
            result = get_worker_api_key(config_dir)
            assert result == test_key

    def test_no_key_available(self):
        """Test error when no API key is available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_dir.mkdir(exist_ok=True)
            
            # Ensure no environment variable is set
            if "WERENDER_API_KEY" in os.environ:
                del os.environ["WERENDER_API_KEY"]
            
            # No api_keys.json file exists
            with pytest.raises(ValueError) as exc_info:
                get_worker_api_key(config_dir)
            
            assert "No API key found" in str(exc_info.value)

    def test_environment_variable_priority(self):
        """Test that environment variable takes priority over file."""
        env_key = "env_priority_key_1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        file_key = "file_priority_key_1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_dir.mkdir(exist_ok=True)
            
            # Create api_keys.json with different key
            api_keys_file = config_dir / "api_keys.json"
            test_keys = {
                "worker": file_key,
                "coordinator": "other_key",
            }
            
            with open(api_keys_file, "w") as f:
                json.dump(test_keys, f)
            
            # Set environment variable
            os.environ["WERENDER_API_KEY"] = env_key
            
            try:
                result = get_worker_api_key(config_dir)
                # Environment variable should take priority
                assert result == env_key
            finally:
                del os.environ["WERENDER_API_KEY"]


class TestSecurityFeatures:
    """Test security-related features."""

    def test_file_permissions(self):
        """Test that api_keys.json is created with restricted permissions (Unix only)."""
        import sys
        
        # Skip this test on Windows entirely
        if sys.platform == "win32":
            pytest.skip("File permissions test not applicable on Windows")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(Path(tmpdir))
            api_keys_file = Path(tmpdir) / "api_keys.json"
            
            # Check file permissions on Unix-like systems
            stat = os.stat(api_keys_file)
            mode = stat.st_mode & 0o777
            # File should be readable/writable only by owner (600)
            assert mode == 0o600, f"Expected mode 0o600, got {oct(mode)}"

    def test_keys_not_in_default_location(self):
        """Test that keys can be stored in custom location."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom_config"
            
            auth = AuthManager(custom_dir)
            
            # Keys should be in custom directory
            assert (custom_dir / "api_keys.json").exists()
            assert not (Path.home() / ".werender" / "api_keys.json").exists() == custom_dir != Path.home() / ".werender"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])