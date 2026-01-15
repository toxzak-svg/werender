"""System utilities for WeRender."""

from dataclasses import dataclass
from typing import Optional

import psutil
import logging

logger = logging.getLogger(__name__)


@dataclass
class SystemSpecs:
    """System specifications for a worker node."""

    hostname: str
    """Machine hostname."""

    cpu_cores: int
    """Number of CPU cores."""

    cpu_threads: int
    """Number of CPU threads."""

    ram_gb: float
    """Total RAM in gigabytes."""

    gpu_name: Optional[str] = None
    """GPU name if available."""

    gpu_vram_gb: Optional[float] = None
    """GPU VRAM in gigabytes if available."""


@dataclass
class SystemStatus:
    """Current system status."""

    cpu_percent: float
    """Current CPU usage percentage."""

    ram_percent: float
    """Current RAM usage percentage."""

    ram_used_gb: float
    """RAM currently in use (GB)."""

    ram_available_gb: float
    """RAM available (GB)."""


def get_system_specs() -> SystemSpecs:
    """
    Get the system specifications.

    Returns:
        SystemSpecs with hardware information.
    """
    import socket

    cpu_count = psutil.cpu_count(logical=False) or 1
    cpu_threads = psutil.cpu_count(logical=True) or 1
    memory = psutil.virtual_memory()

    # Try to detect GPU (Windows only for now)
    gpu_name = None
    gpu_vram = None

    try:
        # Try nvidia-smi for NVIDIA GPUs
        import subprocess

        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 2:
                gpu_name = parts[0]
                gpu_vram = float(parts[1]) / 1024  # Convert MB to GB
    except Exception as e:
        logger.debug(f"GPU detection failed: {e}")

    return SystemSpecs(
        hostname=socket.gethostname(),
        cpu_cores=cpu_count,
        cpu_threads=cpu_threads,
        ram_gb=round(memory.total / (1024**3), 1),
        gpu_name=gpu_name,
        gpu_vram_gb=round(gpu_vram, 1) if gpu_vram else None,
    )


def get_system_status() -> SystemStatus:
    """
    Get current system status.

    Returns:
        SystemStatus with current usage metrics.
    """
    cpu = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    return SystemStatus(
        cpu_percent=cpu,
        ram_percent=memory.percent,
        ram_used_gb=round(memory.used / (1024**3), 2),
        ram_available_gb=round(memory.available / (1024**3), 2),
    )
