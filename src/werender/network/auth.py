"""Authentication and authorization for WeRender."""

import os
import secrets
import hashlib
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader


class AuthManager:
    """Manages API keys and authentication."""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the authentication manager.

        Args:
            config_dir: Directory to store auth files (defaults to ~/.werender)
        """
        self.config_dir = config_dir or Path.home() / ".werender"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.api_keys_file = self.config_dir / "api_keys.json"

        # Load existing API keys or create new ones
        self.api_keys = self._load_api_keys()

    def _load_api_keys(self) -> dict:
        """Load API keys from storage, creating defaults if none exist."""
        import json

        if self.api_keys_file.exists():
            try:
                with open(self.api_keys_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load API keys: {e}")
                return {}

        # Create default API keys only on first run
        default_keys = self._generate_default_keys()
        self._save_api_keys(default_keys)
        return default_keys

    def _generate_default_keys(self) -> dict:
        """Generate default API keys for initial setup."""
        # Generate a secure coordinator key
        coordinator_key = self._generate_api_key("coordinator")

        # Generate a worker key (workers can share this or have individual keys)
        worker_key = self._generate_api_key("worker")

        return {
            "coordinator": coordinator_key,
            "worker": worker_key,
            "version": 1,
            "created_at": time.time(),
        }

    def _generate_api_key(self, name: str) -> str:
        """Generate a secure API key."""
        # Generate 32 bytes of random data and encode as hex
        raw_key = secrets.token_hex(32)
        return raw_key

    def _save_api_keys(self, keys: dict) -> None:
        """Save API keys to storage."""
        import json

        with open(self.api_keys_file, "w") as f:
            json.dump(keys, f, indent=2)

        # Set restrictive permissions on Unix-like systems
        try:
            os.chmod(self.api_keys_file, 0o600)
        except Exception:
            pass  # Windows doesn't support chmod like this

    def validate_key(self, api_key: str, required_type: Optional[str] = None) -> bool:
        """
        Validate an API key.

        Args:
            api_key: The API key to validate
            required_type: Required key type (e.g., 'coordinator', 'worker')

        Returns:
            True if the key is valid, False otherwise
        """
        # Check against stored keys
        for key_type, stored_key in self.api_keys.items():
            if stored_key == api_key:
                if required_type is None or key_type == required_type:
                    return True

        return False

    def get_key(self, key_type: str) -> Optional[str]:
        """
        Get an API key by type.

        Args:
            key_type: Type of key to retrieve (e.g., 'coordinator', 'worker')

        Returns:
            The API key string, or None if not found
        """
        return self.api_keys.get(key_type)

    def add_worker_key(self, worker_id: str) -> str:
        """
        Generate a new API key for a specific worker.

        Args:
            worker_id: Unique identifier for the worker (e.g., 'worker_host_01')

        Returns:
            The generated API key
        """
        key = self._generate_api_key(f"worker_{worker_id}")
        # Add to in-memory dict
        self.api_keys[worker_id] = key
        # Save to file (preserves all existing keys)
        self._save_api_keys(self.api_keys)
        return key

    def revoke_key(self, key_type: str) -> bool:
        """
        Revoke an API key.

        Args:
            key_type: Type of key to revoke (e.g., 'worker_host_01', 'worker')

        Returns:
            True if revoked, False if not found
        """
        if key_type in self.api_keys:
            del self.api_keys[key_type]
            # Save to file (preserves all remaining keys)
            self._save_api_keys(self.api_keys)
            return True
        return False

    def print_setup_instructions(self) -> None:
        """Print instructions for setting up authentication."""
        print("\n" + "=" * 60)
        print("WeRender Authentication Setup")
        print("=" * 60)
        print("\nAPI keys have been generated and stored in:")
        print(f"  {self.api_keys_file}")
        print("\nWorkers must be configured with the worker API key:")
        print(f"  Worker API Key: {self.api_keys.get('worker', 'Not found')}")
        print("\nFor production use, you should:")
        print("  1. Keep API keys secret and never commit to version control")
        print("  2. Use environment variables for worker deployment")
        print("  3. Generate unique keys for each worker using add_worker_key()")
        print("  4. Regularly rotate keys using revoke_key() and generate new ones")
        print("=" * 60 + "\n")


def get_api_key_dependency(auth_manager: AuthManager, key_type: Optional[str] = None):
    """
    Create a FastAPI dependency for API key authentication.

    Args:
        auth_manager: The authentication manager instance
        key_type: Required key type (e.g., 'coordinator', 'worker')

    Returns:
        A FastAPI dependency function
    """
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required. Provide X-API-Key header.",
            )

        if not auth_manager.validate_key(api_key, key_type):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API key",
            )

        return api_key

    return verify_api_key


# Convenience function to get API key from environment or config
def get_worker_api_key(config_dir: Optional[Path] = None) -> str:
    """
    Get the worker API key for a worker node.

    This function first checks the WERENDER_API_KEY environment variable,
    then falls back to reading from the api_keys.json file.

    Args:
        config_dir: Directory containing api_keys.json (defaults to ~/.werender)

    Returns:
        The worker API key

    Raises:
        ValueError: If no API key is found
    """
    # Check environment variable first
    env_key = os.environ.get("WERENDER_API_KEY")
    if env_key:
        return env_key

    # Fall back to file
    if config_dir is None:
        config_dir = Path.home() / ".werender"

    api_keys_file = config_dir / "api_keys.json"
    if not api_keys_file.exists():
        raise ValueError(
            "No API key found. Either set WERENDER_API_KEY environment variable "
            "or ensure the coordinator has generated api_keys.json"
        )

    import json

    with open(api_keys_file, "r") as f:
        keys = json.load(f)

    worker_key = keys.get("worker")
    if not worker_key:
        raise ValueError("No worker API key found in api_keys.json")

    return worker_key