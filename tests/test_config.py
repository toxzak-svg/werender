"""Tests for configuration module."""

from pathlib import Path

import pytest

from werender.core.config import (
    BlenderConfig,
    NetworkConfig,
    RenderConfig,
    multirenderConfig,
)


def test_blender_config_defaults():
    """Test BlenderConfig default values."""
    config = BlenderConfig()
    assert config.executable_path == "blender"
    assert config.min_version == "3.6.0"


def test_blender_config_custom():
    """Test BlenderConfig with custom values."""
    config = BlenderConfig(
        executable_path="/custom/path/blender", min_version="4.0.0"
    )
    assert config.executable_path == "/custom/path/blender"
    assert config.min_version == "4.0.0"


def test_network_config_defaults():
    """Test NetworkConfig default values."""
    config = NetworkConfig()
    assert config.service_name == "multirender"
    assert config.service_type == "_renderfarm._tcp.local."
    assert config.api_port == 8420
    assert config.heartbeat_interval == 5.0
    assert config.heartbeat_timeout_count == 3
    assert config.slowdown_threshold == 3.0


def test_network_config_custom():
    """Test NetworkConfig with custom values."""
    config = NetworkConfig(
        service_name="custom_render",
        service_type="_custom._tcp.local.",
        api_port=9000,
        heartbeat_interval=10.0,
        heartbeat_timeout_count=5,
        slowdown_threshold=5.0,
    )
    assert config.service_name == "custom_render"
    assert config.service_type == "_custom._tcp.local."
    assert config.api_port == 9000
    assert config.heartbeat_interval == 10.0
    assert config.heartbeat_timeout_count == 5
    assert config.slowdown_threshold == 5.0


def test_render_config_defaults():
    """Test RenderConfig default values."""
    config = RenderConfig()
    assert config.output_format == "PNG"
    assert config.temp_directory is None


def test_render_config_custom():
    """Test RenderConfig with custom values."""
    config = RenderConfig(
        output_format="JPEG", temp_directory=Path("/tmp/render")
    )
    assert config.output_format == "JPEG"
    assert config.temp_directory == Path("/tmp/render")


def test_multirender_config_defaults():
    """Test multirenderConfig default values."""
    config = multirenderConfig()
    assert isinstance(config.blender, BlenderConfig)
    assert isinstance(config.network, NetworkConfig)
    assert isinstance(config.render, RenderConfig)

    assert config.blender.executable_path == "blender"
    assert config.network.api_port == 8420
    assert config.render.output_format == "PNG"


def test_multirender_config_custom():
    """Test multirenderConfig with custom sub-configurations."""
    config = multirenderConfig(
        blender=BlenderConfig(executable_path="/path/to/blender"),
        network=NetworkConfig(api_port=9999),
        render=RenderConfig(output_format="EXR"),
    )
    assert config.blender.executable_path == "/path/to/blender"
    assert config.network.api_port == 9999
    assert config.render.output_format == "EXR"


def test_multirender_config_default_classmethod():
    """Test multirenderConfig.default() class method."""
    config = multirenderConfig.default()
    assert isinstance(config, multirenderConfig)
    assert isinstance(config.blender, BlenderConfig)
    assert isinstance(config.network, NetworkConfig)
    assert isinstance(config.render, RenderConfig)


def test_config_serialization():
    """Test configuration can be serialized to dict."""
    config = multirenderConfig()
    data = config.model_dump()

    assert "blender" in data
    assert "network" in data
    assert "render" in data

    assert data["blender"]["executable_path"] == "blender"
    assert data["network"]["api_port"] == 8420
    assert data["render"]["output_format"] == "PNG"


def test_config_from_dict():
    """Test configuration can be created from dict."""
    data = {
        "blender": {"executable_path": "/custom/blender"},
        "network": {"api_port": 8888},
        "render": {"output_format": "TIFF"},
    }
    config = multirenderConfig(**data)

    assert config.blender.executable_path == "/custom/blender"
    assert config.network.api_port == 8888
    assert config.render.output_format == "TIFF"