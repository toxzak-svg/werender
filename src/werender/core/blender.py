"""Blender CLI wrapper for WeRender."""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RenderResult:
    """Result of a render operation."""

    success: bool
    """Whether the render succeeded."""

    frame: int
    """Frame number that was rendered."""

    output_file: Optional[Path] = None
    """Path to the output file if successful."""

    render_time: float = 0.0
    """Time taken to render in seconds."""

    error_message: Optional[str] = None
    """Error message if render failed."""


class BlenderNotFoundError(Exception):
    """Raised when Blender executable cannot be found."""


class BlenderVersionError(Exception):
    """Raised when Blender version is incompatible."""


class BlenderRenderer:
    """Wrapper for Blender command-line rendering."""

    def __init__(self, blender_path: str = "blender"):
        """
        Initialize the Blender renderer.

        Args:
            blender_path: Path to Blender executable. Defaults to 'blender'
                         which assumes it's available in system PATH.
        """
        self.blender_path = self._find_blender(blender_path)
        self._version: Optional[str] = None

    def _find_blender(self, blender_path: str) -> str:
        """
        Find the Blender executable.

        Args:
            blender_path: User-provided path or 'blender' for PATH lookup.

        Returns:
            Absolute path to Blender executable.

        Raises:
            BlenderNotFoundError: If Blender cannot be found.
        """
        # Check if it's a direct path
        if Path(blender_path).exists():
            return str(Path(blender_path).resolve())

        # Try to find in PATH
        found = shutil.which(blender_path)
        if found:
            return found

        # Common installation paths on Windows
        common_paths = [
            Path("C:/Program Files/Blender Foundation"),
            Path("C:/Program Files (x86)/Blender Foundation"),
            Path.home() / "AppData/Roaming/Blender Foundation",
        ]

        for base_path in common_paths:
            if base_path.exists():
                # Find latest Blender version directory
                blender_dirs = sorted(
                    [d for d in base_path.iterdir() if d.is_dir() and d.name.startswith("Blender")],
                    reverse=True,
                )
                for blender_dir in blender_dirs:
                    exe_path = blender_dir / "blender.exe"
                    if exe_path.exists():
                        return str(exe_path)

        raise BlenderNotFoundError(
            f"Could not find Blender at '{blender_path}' or in common installation paths. "
            "Please install Blender or provide the full path to the executable."
        )

    def get_version(self) -> str:
        """
        Get the Blender version.

        Returns:
            Version string like "4.0.0".

        Raises:
            BlenderVersionError: If version cannot be determined.
        """
        if self._version:
            return self._version

        try:
            result = subprocess.run(
                [self.blender_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Parse version from output like "Blender 4.0.0"
            match = re.search(r"Blender (\d+\.\d+\.\d+)", result.stdout)
            if match:
                self._version = match.group(1)
                return self._version

            raise BlenderVersionError(f"Could not parse version from: {result.stdout}")

        except subprocess.TimeoutExpired:
            raise BlenderVersionError("Blender version check timed out")
        except Exception as e:
            raise BlenderVersionError(f"Failed to get Blender version: {e}")

    def render_frame(
        self,
        blend_file: Path,
        frame: int,
        output_dir: Path,
        output_format: str = "PNG",
    ) -> RenderResult:
        """
        Render a single frame from a .blend file.

        Args:
            blend_file: Path to the .blend file.
            frame: Frame number to render.
            output_dir: Directory to save the rendered frame.
            output_format: Output format (PNG, JPEG, EXR, etc.).

        Returns:
            RenderResult with success status and output file path.
        """
        import time

        blend_file = Path(blend_file).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Blender outputs files with frame numbers padded to 4 digits
        # e.g., "0001.png" for frame 1
        output_pattern = output_dir / "####"

        # Build the Blender command
        cmd = [
            self.blender_path,
            "-b",  # Background mode (no GUI)
            str(blend_file),
            "-o",
            str(output_pattern),
            "-F",
            output_format.upper(),
            "-f",
            str(frame),
        ]

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout per frame
            )

            render_time = time.time() - start_time

            # Find the output file
            ext = self._format_to_extension(output_format)
            expected_output = output_dir / f"{frame:04d}{ext}"

            if expected_output.exists():
                return RenderResult(
                    success=True,
                    frame=frame,
                    output_file=expected_output,
                    render_time=render_time,
                )

            # Check for errors in output
            if result.returncode != 0:
                return RenderResult(
                    success=False,
                    frame=frame,
                    render_time=render_time,
                    error_message=f"Blender exited with code {result.returncode}: {result.stderr}",
                )

            return RenderResult(
                success=False,
                frame=frame,
                render_time=render_time,
                error_message=f"Output file not found at {expected_output}",
            )

        except subprocess.TimeoutExpired:
            return RenderResult(
                success=False,
                frame=frame,
                render_time=time.time() - start_time,
                error_message="Render timed out after 1 hour",
            )
        except Exception as e:
            return RenderResult(
                success=False,
                frame=frame,
                error_message=str(e),
            )

    def pack_resources(self, blend_file: Path, output_path: Optional[Path] = None) -> Path:
        """
        Pack all external resources into the .blend file.

        This creates a copy of the file with all textures, images, and other
        external resources embedded, eliminating path dependency issues.

        Args:
            blend_file: Path to the original .blend file.
            output_path: Optional path for the packed file. If None, creates
                        a temp file with '_packed' suffix.

        Returns:
            Path to the packed .blend file.

        Raises:
            RuntimeError: If packing fails.
        """
        blend_file = Path(blend_file).resolve()

        if output_path is None:
            # Create packed file in temp directory
            temp_dir = Path(tempfile.gettempdir()) / "werender"
            temp_dir.mkdir(exist_ok=True)
            output_path = temp_dir / f"{blend_file.stem}_packed.blend"

        # Python script to run inside Blender
        pack_script = """
import bpy
import sys

try:
    # Pack all external data
    bpy.ops.file.pack_all()
    
    # Save to the output path (passed as last argument)
    output_path = sys.argv[-1]
    bpy.ops.wm.save_as_mainfile(filepath=output_path)
    
    print("PACK_SUCCESS")
except Exception as e:
    print(f"PACK_ERROR: {e}")
    sys.exit(1)
"""

        # Write temp script
        script_path = Path(tempfile.gettempdir()) / "werender_pack.py"
        script_path.write_text(pack_script)

        try:
            result = subprocess.run(
                [
                    self.blender_path,
                    "-b",
                    str(blend_file),
                    "--python",
                    str(script_path),
                    "--",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for packing
            )

            if "PACK_SUCCESS" in result.stdout and output_path.exists():
                return output_path

            raise RuntimeError(f"Failed to pack resources: {result.stderr}")

        except subprocess.TimeoutExpired:
            raise RuntimeError("Packing resources timed out after 5 minutes")
        finally:
            # Clean up temp script
            if script_path.exists():
                script_path.unlink()

    def _format_to_extension(self, output_format: str) -> str:
        """Convert Blender format name to file extension."""
        format_map = {
            "PNG": ".png",
            "JPEG": ".jpg",
            "OPEN_EXR": ".exr",
            "OPEN_EXR_MULTILAYER": ".exr",
            "TIFF": ".tif",
            "BMP": ".bmp",
            "TARGA": ".tga",
            "TARGA_RAW": ".tga",
        }
        return format_map.get(output_format.upper(), ".png")
