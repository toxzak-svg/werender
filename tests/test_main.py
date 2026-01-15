"""Tests for main CLI module."""

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from werender.main import cmd_coordinator, cmd_info, cmd_render, cmd_worker, main


@pytest.fixture
def mock_temp_file(tmp_path):
    """Create a temporary .blend file for testing."""
    blend_file = tmp_path / "test.blend"
    blend_file.touch()
    return blend_file


class TestCmdRender:
    """Tests for cmd_render function."""

    @patch("werender.main.BlenderRenderer")
    def test_cmd_render_success(self, mock_renderer, mock_temp_file, tmp_path):
        """Test successful render command."""
        # Mock the renderer
        mock_render_instance = Mock()
        mock_render_instance.get_version.return_value = "3.6.0"
        mock_render_instance.render_frame.return_value = Mock(
            success=True,
            render_time=5.0,
            output_file="frame_0001.png",
        )
        mock_renderer.return_value = mock_render_instance

        # Create args
        args = argparse.Namespace(
            file=str(mock_temp_file),
            frames="1-3",
            output=str(tmp_path / "output"),
            blender=None,
        )

        result = cmd_render(args)

        assert result == 0
        assert mock_render_instance.render_frame.call_count == 3

    @patch("werender.main.BlenderRenderer")
    def test_cmd_render_file_not_found(self, mock_renderer, tmp_path):
        """Test render command with non-existent file."""
        args = argparse.Namespace(
            file=str(tmp_path / "nonexistent.blend"),
            frames="1",
            output=str(tmp_path / "output"),
            blender=None,
        )

        result = cmd_render(args)

        assert result == 1
        mock_renderer.assert_not_called()

    @patch("werender.main.BlenderRenderer", side_effect=Exception("Blender not found"))
    def test_cmd_render_blender_not_found(self, mock_renderer, mock_temp_file, tmp_path):
        """Test render command when Blender is not found."""
        args = argparse.Namespace(
            file=str(mock_temp_file),
            frames="1",
            output=str(tmp_path / "output"),
            blender=None,
        )

        result = cmd_render(args)

        assert result == 1

    @patch("werender.main.BlenderRenderer")
    def test_cmd_render_partial_failure(self, mock_renderer, mock_temp_file, tmp_path):
        """Test render command with some frame failures."""
        # Mock renderer with mixed success
        mock_render_instance = Mock()
        mock_render_instance.get_version.return_value = "3.6.0"

        def side_effect(*args, **kwargs):
            call_count = mock_render_instance.render_frame.call_count
            return Mock(
                success=(call_count < 2),  # First 2 succeed, 3rd fails
                render_time=5.0,
                output_file="frame_0001.png" if call_count < 2 else None,
                error_message="Test error" if call_count >= 2 else None,
            )

        mock_render_instance.render_frame.side_effect = side_effect
        mock_renderer.return_value = mock_render_instance

        args = argparse.Namespace(
            file=str(mock_temp_file),
            frames="1-3",
            output=str(tmp_path / "output"),
            blender=None,
        )

        result = cmd_render(args)

        assert result == 1  # Should return 1 if any frame failed

    @patch("werender.main.BlenderRenderer")
    def test_cmd_render_single_frame(self, mock_renderer, mock_temp_file, tmp_path):
        """Test render command with single frame."""
        mock_render_instance = Mock()
        mock_render_instance.get_version.return_value = "3.6.0"
        mock_render_instance.render_frame.return_value = Mock(
            success=True,
            render_time=5.0,
            output_file="frame_0005.png",
        )
        mock_renderer.return_value = mock_render_instance

        args = argparse.Namespace(
            file=str(mock_temp_file),
            frames="5",  # Single frame
            output=str(tmp_path / "output"),
            blender=None,
        )

        result = cmd_render(args)

        assert result == 0
        assert mock_render_instance.render_frame.call_count == 1


class TestCmdCoordinator:
    """Tests for cmd_coordinator function."""

    @patch("werender.main.CoordinatorServer")
    def test_cmd_coordinator_default_port(self, mock_coordinator):
        """Test coordinator command with default port."""
        mock_instance = Mock()
        mock_coordinator.return_value = mock_instance

        args = argparse.Namespace(port=8420, file=None, frames=None)

        result = cmd_coordinator(args)

        assert result == 0
        mock_coordinator.assert_called_once_with(port=8420)
        mock_instance.run.assert_called_once()

    @patch("werender.main.CoordinatorServer")
    def test_cmd_coordinator_custom_port(self, mock_coordinator):
        """Test coordinator command with custom port."""
        mock_instance = Mock()
        mock_coordinator.return_value = mock_instance

        args = argparse.Namespace(port=9999, file=None, frames=None)

        result = cmd_coordinator(args)

        assert result == 0
        mock_coordinator.assert_called_once_with(port=9999)


class TestCmdWorker:
    """Tests for cmd_worker function."""

    @patch("werender.main.WorkerNode")
    def test_cmd_worker_default_name(self, mock_worker):
        """Test worker command with default name."""
        mock_instance = Mock()
        mock_worker.return_value = mock_instance

        args = argparse.Namespace(name=None)

        result = cmd_worker(args)

        assert result == 0
        mock_worker.assert_called_once_with(name=None)
        mock_instance.start.assert_called_once()

    @patch("werender.main.WorkerNode")
    def test_cmd_worker_custom_name(self, mock_worker):
        """Test worker command with custom name."""
        mock_instance = Mock()
        mock_worker.return_value = mock_instance

        args = argparse.Namespace(name="my-worker")

        result = cmd_worker(args)

        assert result == 0
        mock_worker.assert_called_once_with(name="my-worker")


class TestCmdInfo:
    """Tests for cmd_info function."""

    @patch("werender.main.BlenderRenderer")
    @patch("werender.main.get_system_specs")
    def test_cmd_info_success(self, mock_specs, mock_renderer):
        """Test info command with Blender found."""
        # Mock system specs
        mock_specs.return_value = Mock(
            hostname="test-host",
            cpu_cores=8,
            cpu_threads=16,
            ram_gb=32.0,
            gpu_name="NVIDIA RTX 3080",
            gpu_vram_gb=10.0,
        )

        # Mock Blender renderer
        mock_render_instance = Mock()
        mock_render_instance.get_version.return_value = "3.6.0"
        mock_renderer.return_value = mock_render_instance

        args = argparse.Namespace()

        result = cmd_info(args)

        assert result == 0
        mock_specs.assert_called_once()

    @patch("werender.main.BlenderRenderer", side_effect=Exception("Not found"))
    @patch("werender.main.get_system_specs")
    def test_cmd_info_no_blender(self, mock_specs, mock_renderer):
        """Test info command without Blender."""
        # Mock system specs without GPU
        mock_specs.return_value = Mock(
            hostname="test-host",
            cpu_cores=4,
            cpu_threads=8,
            ram_gb=16.0,
            gpu_name=None,
            gpu_vram_gb=None,
        )

        args = argparse.Namespace()

        result = cmd_info(args)

        assert result == 0

    @patch("werender.main.BlenderRenderer")
    @patch("werender.main.get_system_specs")
    def test_cmd_info_no_gpu(self, mock_specs, mock_renderer):
        """Test info command without GPU."""
        # Mock system specs without GPU
        mock_specs.return_value = Mock(
            hostname="test-host",
            cpu_cores=4,
            cpu_threads=8,
            ram_gb=16.0,
            gpu_name=None,
            gpu_vram_gb=None,
        )

        # Mock Blender renderer
        mock_render_instance = Mock()
        mock_render_instance.get_version.return_value = "4.0.0"
        mock_renderer.return_value = mock_render_instance

        args = argparse.Namespace()

        result = cmd_info(args)

        assert result == 0


class TestMain:
    """Tests for main function."""

    @patch("werender.main.cmd_render")
    def test_main_render_command(self, mock_cmd_render):
        """Test main with render command."""
        mock_cmd_render.return_value = 0

        with patch.object(sys, "argv", ["werender", "render", "-f", "test.blend"]):
            result = main()

        assert result == 0
        mock_cmd_render.assert_called_once()

    @patch("werender.main.cmd_coordinator")
    def test_main_coordinator_command(self, mock_cmd_coordinator):
        """Test main with coordinator command."""
        mock_cmd_coordinator.return_value = 0

        with patch.object(sys, "argv", ["werender", "coordinator"]):
            result = main()

        assert result == 0
        mock_cmd_coordinator.assert_called_once()

    @patch("werender.main.cmd_worker")
    def test_main_worker_command(self, mock_cmd_worker):
        """Test main with worker command."""
        mock_cmd_worker.return_value = 0

        with patch.object(sys, "argv", ["werender", "worker"]):
            result = main()

        assert result == 0
        mock_cmd_worker.assert_called_once()

    @patch("werender.main.cmd_info")
    def test_main_info_command(self, mock_cmd_info):
        """Test main with info command."""
        mock_cmd_info.return_value = 0

        with patch.object(sys, "argv", ["werender", "info"]):
            result = main()

        assert result == 0
        mock_cmd_info.assert_called_once()

    @patch("sys.stdout")
    def test_main_no_command(self, mock_stdout):
        """Test main with no command (shows help)."""
        with patch.object(sys, "argv", ["werender"]):
            result = main()

        assert result == 0