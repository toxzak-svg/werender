
import pytest
from unittest.mock import MagicMock, patch
from werender.utils.system import get_system_specs, get_system_status

def test_get_system_specs_structure():
    """Test that get_system_specs returns a valid SystemSpecs object."""
    specs = get_system_specs()
    assert specs.hostname
    assert specs.cpu_cores > 0
    assert specs.cpu_threads > 0
    assert specs.ram_gb > 0

@patch("subprocess.run")
def test_get_system_specs_gpu_success(mock_run):
    """Test successful GPU detection."""
    # Mock successful nvidia-smi output
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="NVIDIA GeForce RTX 3080, 10240\n"
    )
    
    specs = get_system_specs()
    assert specs.gpu_name == "NVIDIA GeForce RTX 3080"
    assert specs.gpu_vram_gb == 10.0

@patch("subprocess.run")
def test_get_system_specs_gpu_failure(mock_run):
    """Test GPU detection failure/missing."""
    # Mock failed execution
    mock_run.side_effect = Exception("Command not found")
    
    # Needs to capture logging if we want to verify the log message, 
    # but primarily we ensure it doesn't crash and returns valid specs without GPU
    specs = get_system_specs()
    assert specs.gpu_name is None
    assert specs.gpu_vram_gb is None

def test_get_system_status_structure():
    """Test that get_system_status returns valid status."""
    status = get_system_status()
    assert isinstance(status.cpu_percent, float)
    assert isinstance(status.ram_percent, float)
    assert status.ram_used_gb > 0
    assert status.ram_available_gb >= 0
