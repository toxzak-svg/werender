"""Tests for the Blender CLI wrapper."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from werender.core.blender import (
    BlenderNotFoundError,
    BlenderRenderer,
    BlenderVersionError,
    RenderResult,
)


class TestBlenderRenderer:
    """Tests for BlenderRenderer class."""

    def test_version_parsing(self):
        """Test that version is correctly parsed from Blender output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Blender 4.0.0\n  build date: 2023-11-14",
                returncode=0,
            )
            with patch("shutil.which", return_value="/usr/bin/blender"):
                renderer = BlenderRenderer()
                version = renderer.get_version()
                assert version == "4.0.0"

    def test_blender_not_found_raises_error(self):
        """Test that BlenderNotFoundError is raised when Blender is not found."""
        with patch("shutil.which", return_value=None):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(BlenderNotFoundError):
                    BlenderRenderer("nonexistent-blender")

    def test_render_result_dataclass(self):
        """Test RenderResult dataclass."""
        result = RenderResult(
            success=True,
            frame=42,
            output_file=Path("/output/0042.png"),
            render_time=15.5,
        )
        assert result.success is True
        assert result.frame == 42
        assert result.render_time == 15.5

    def test_format_to_extension(self):
        """Test format to extension conversion."""
        with patch("shutil.which", return_value="/usr/bin/blender"):
            renderer = BlenderRenderer()
            assert renderer._format_to_extension("PNG") == ".png"
            assert renderer._format_to_extension("JPEG") == ".jpg"
            assert renderer._format_to_extension("OPEN_EXR") == ".exr"
            assert renderer._format_to_extension("unknown") == ".png"  # Default


class TestRenderFrame:
    """Tests for frame rendering."""

    def test_render_frame_success(self):
        """Test successful frame render."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            
            # Create a fake output file that Blender would produce
            expected_output = output_dir / "0001.png"

            with patch("shutil.which", return_value="/usr/bin/blender"):
                with patch("subprocess.run") as mock_run:
                    # Simulate subprocess completion
                    mock_run.return_value = MagicMock(returncode=0, stderr="")
                    
                    # Create the output file to simulate Blender's output
                    expected_output.parent.mkdir(parents=True, exist_ok=True)
                    expected_output.write_bytes(b"fake png data")

                    renderer = BlenderRenderer()
                    result = renderer.render_frame(
                        blend_file=Path("/fake/test.blend"),
                        frame=1,
                        output_dir=output_dir,
                    )

                    assert result.success is True
                    assert result.frame == 1
                    assert result.output_file == expected_output

    def test_render_frame_creates_output_dir(self):
        """Test that render_frame creates output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "nested" / "output"

            with patch("shutil.which", return_value="/usr/bin/blender"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stderr="")

                    renderer = BlenderRenderer()
                    # Will fail because output file won't exist, but should create dir
                    renderer.render_frame(
                        blend_file=Path("/fake/test.blend"),
                        frame=1,
                        output_dir=output_dir,
                    )

                    assert output_dir.exists()
