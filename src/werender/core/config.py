"""Configuration settings for multirender."""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class BlenderConfig(BaseModel):
    """Configuration for Blender executable."""

    executable_path: str = "blender"
    """Path to Blender executable. Defaults to 'blender' (assumes it's in PATH)."""

    min_version: str = "3.6.0"
    """Minimum required Blender version."""


class NetworkConfig(BaseModel):
    """Configuration for network settings."""

    service_name: str = "multirender"
    """Name for mDNS service registration."""

    service_type: str = "_renderfarm._tcp.local."
    """mDNS service type for discovery."""

    api_port: int = 8420
    """Port for the HTTP/WebSocket API."""

    heartbeat_interval: float = 5.0
    """Seconds between worker heartbeat pings."""

    heartbeat_timeout_count: int = 3
    """Number of missed heartbeats before marking worker as dead."""

    slowdown_threshold: float = 3.0
    """Mark worker slow if render takes this multiple of average time (300%)."""


class RenderConfig(BaseModel):
    """Configuration for render settings."""

    output_format: str = "PNG"
    """Default output format for rendered frames."""

    temp_directory: Optional[Path] = None
    """Temporary directory for downloads/renders. Uses system temp if None."""


class multirenderConfig(BaseModel):
    """Main configuration for multirender."""

    blender: BlenderConfig = BlenderConfig()
    network: NetworkConfig = NetworkConfig()
    render: RenderConfig = RenderConfig()

    @classmethod
    def default(cls) -> "multirenderConfig":
        """Create default configuration."""
        return cls()
