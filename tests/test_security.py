"""Tests for security features in WeRender."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from werender.network.coordinator import CoordinatorServer
from werender.network.auth import AuthManager
from werender.network.security import BlendFileValidator, RateLimiter


class TestAuthManager:
    """Test authentication manager functionality."""

    def test_api_key_generation(self):
        """Test that API keys are generated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_manager = AuthManager(Path(tmpdir))
            
            # Check that keys were generated
            assert "coordinator" in auth_manager.api_keys
            assert "worker" in auth_manager.api_keys
            
            # Check key length (64 hex chars = 32 bytes)
            assert len(auth_manager.api_keys["coordinator"]) == 64
            assert len(auth_manager.api_keys["worker"]) == 64

    def test_key_validation(self):
        """Test API key validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_manager = AuthManager(Path(tmpdir))
            
            coordinator_key = auth_manager.api_keys["coordinator"]
            worker_key = auth_manager.api_keys["worker"]
            
            # Valid keys should pass
            assert auth_manager.validate_key(coordinator_key, "coordinator")
            assert auth_manager.validate_key(worker_key, "worker")
            
            # Wrong key type should fail
            assert not auth_manager.validate_key(coordinator_key, "worker")
            
            # Invalid key should fail
            assert not auth_manager.validate_key("invalid_key", "coordinator")

    def test_worker_key_management(self):
        """Test adding and revoking worker keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_manager = AuthManager(Path(tmpdir))
            
            # Add a worker-specific key
            worker_key = auth_manager.add_worker_key("worker_host_01")
            assert len(worker_key) == 64
            assert auth_manager.validate_key(worker_key, "worker_host_01")
            
            # Revoke the key
            assert auth_manager.revoke_key("worker_host_01")
            assert not auth_manager.validate_key(worker_key, "worker_host_01")

    def test_get_key(self):
        """Test retrieving API keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_manager = AuthManager(Path(tmpdir))
            
            # Get existing keys
            coordinator_key = auth_manager.get_key("coordinator")
            worker_key = auth_manager.get_key("worker")
            
            assert coordinator_key is not None
            assert worker_key is not None
            
            # Get non-existent key
            assert auth_manager.get_key("nonexistent") is None


class TestBlendFileValidator:
    """Test .blend file validation."""

    def test_validate_blend_file_with_magic_bytes(self):
        """Test validation of a valid .blend file with magic bytes."""
        with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as f:
            # Write valid .blend header
            # BLENDER_v294
            f.write(b"BLENDER")
            f.write(b"-")  # 64-bit
            f.write(b"v")  # little-endian
            f.write(b"294")  # version
            f.write(b"\x00" * 100)  # Some dummy data
            f.flush()
            f.close()
            
            try:
                is_valid, error = BlendFileValidator.validate_blend_file(Path(f.name))
                assert is_valid, f"Valid file was rejected: {error}"
                assert error is None
            finally:
                Path(f.name).unlink()

    def test_validate_blend_file_invalid_magic_bytes(self):
        """Test that files without BLENDER magic bytes are rejected."""
        with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as f:
            # Write invalid header (must be at least 12 bytes for header check)
            f.write(b"INVALID" + b"\x00" * 5)
            f.flush()
            f.close()
            
            try:
                is_valid, error = BlendFileValidator.validate_blend_file(Path(f.name))
                assert not is_valid
                assert "missing magic bytes" in error.lower()
            finally:
                Path(f.name).unlink()

    def test_validate_blend_file_wrong_extension(self):
        """Test that non-.blend files are rejected."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"BLENDER-v294")
            f.flush()
            f.close()
            
            try:
                is_valid, error = BlendFileValidator.validate_blend_file(Path(f.name))
                assert not is_valid
                assert "extension" in error.lower()
            finally:
                Path(f.name).unlink()

    def test_validate_blend_file_too_large(self):
        """Test that files exceeding size limit are rejected."""
        with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as f:
            # Write valid header
            f.write(b"BLENDER-v294")
            # Write dummy data to exceed limit (500MB + 1)
            f.write(b"\x00" * (500 * 1024 * 1024 + 1))
            f.flush()
            f.close()
            
            try:
                is_valid, error = BlendFileValidator.validate_blend_file(Path(f.name))
                assert not is_valid
                assert "too large" in error.lower()
            finally:
                Path(f.name).unlink()

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        # Test path traversal prevention - Path.name removes all path components
        result = BlendFileValidator.sanitize_filename("../../../etc/passwd")
        # Path.name returns just "passwd", then .blend is added
        assert result == "passwd.blend" or result == "passwd"
        
        # Test null bytes
        assert "\0" not in BlendFileValidator.sanitize_filename("test\0file.blend")
        
        # Test non-printable characters
        filename = BlendFileValidator.sanitize_filename("test\x1bfile.blend")
        assert "\x1b" not in filename
        
        # Test .blend extension is added
        assert BlendFileValidator.sanitize_filename("testfile").endswith(".blend")


class TestRateLimiter:
    """Test rate limiting functionality."""

    def test_rate_limiting(self):
        """Test that requests are rate limited."""
        rate_limiter = RateLimiter(max_requests=3, window_seconds=60)
        
        # First 3 requests should be allowed
        for i in range(3):
            assert rate_limiter.is_allowed("test_client")
        
        # 4th request should be blocked
        assert not rate_limiter.is_allowed("test_client")

    def test_rate_limit_reset(self):
        """Test that rate limits can be reset."""
        rate_limiter = RateLimiter(max_requests=1, window_seconds=60)
        
        # First request allowed
        assert rate_limiter.is_allowed("test_client")
        
        # Second request blocked
        assert not rate_limiter.is_allowed("test_client")
        
        # Reset and try again
        rate_limiter.reset("test_client")
        assert rate_limiter.is_allowed("test_client")

    def test_rate_limit_different_clients(self):
        """Test that different clients have independent rate limits."""
        rate_limiter = RateLimiter(max_requests=1, window_seconds=60)
        
        # Client 1 request allowed
        assert rate_limiter.is_allowed("client1")
        
        # Client 1 request blocked
        assert not rate_limiter.is_allowed("client1")
        
        # Client 2 request should still be allowed
        assert rate_limiter.is_allowed("client2")


class TestCoordinatorAuthentication:
    """Test coordinator endpoint authentication."""

    @pytest.fixture
    def coordinator(self):
        """Create a test coordinator server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_dir.mkdir(exist_ok=True)
            
            # Create coordinator with custom config dir
            coordinator = CoordinatorServer(port=8421)
            coordinator.config_dir = config_dir
            coordinator.auth_manager = AuthManager(config_dir)
            # Re-setup routes with new auth_manager
            coordinator.app = FastAPI(title="WeRender Coordinator")
            coordinator._setup_routes()
            yield coordinator

    @pytest.fixture
    def client(self, coordinator):
        """Create a test client for the coordinator."""
        return TestClient(coordinator.app)

    def test_unauthenticated_job_creation_fails(self, client):
        """Test that job creation requires authentication."""
        # Create a dummy .blend file
        with tempfile.NamedTemporaryFile(suffix=".blend") as f:
            f.write(b"BLENDER-v294")
            f.flush()
            f.seek(0)
            
            response = client.post(
                "/api/jobs/create",
                files={"file": ("test.blend", f, "application/octet-stream")},
                data={"frame_start": 1, "frame_end": 10, "name": "Test Job"}
            )
        
        # Should get 401 Unauthorized
        assert response.status_code == 401

    def test_authenticated_job_creation_with_worker_key_fails(self, client, coordinator):
        """Test that job creation requires coordinator key, not worker key."""
        worker_key = coordinator.auth_manager.api_keys["worker"]
        
        # Create a dummy .blend file
        with tempfile.NamedTemporaryFile(suffix=".blend") as f:
            f.write(b"BLENDER-v294")
            f.flush()
            f.seek(0)
            
            response = client.post(
                "/api/jobs/create",
                headers={"X-API-Key": worker_key},
                files={"file": ("test.blend", f, "application/octet-stream")},
                data={"frame_start": 1, "frame_end": 10, "name": "Test Job"}
            )
        
        # Should get 403 Forbidden
        assert response.status_code == 403

    def test_invalid_file_rejected(self, client, coordinator):
        """Test that invalid .blend files are rejected."""
        coordinator_key = coordinator.auth_manager.api_keys["coordinator"]
        
        # Create an invalid file (no magic bytes)
        with tempfile.NamedTemporaryFile(suffix=".blend") as f:
            f.write(b"INVALID FILE")
            f.flush()
            f.seek(0)
            
            response = client.post(
                "/api/jobs/create",
                headers={"X-API-Key": coordinator_key},
                files={"file": ("test.blend", f, "application/octet-stream")},
                data={"frame_start": 1, "frame_end": 10, "name": "Test Job"}
            )
        
        # Should get 400 Bad Request
        assert response.status_code == 400
        assert "Invalid .blend file" in response.json()["detail"]

    def test_authenticated_job_creation_succeeds(self, client, coordinator):
        """Test that authenticated job creation with valid file succeeds."""
        coordinator_key = coordinator.auth_manager.api_keys["coordinator"]
        
        # Create a valid .blend file
        with tempfile.NamedTemporaryFile(suffix=".blend") as f:
            f.write(b"BLENDER-v294")
            f.flush()
            f.seek(0)
            
            response = client.post(
                "/api/jobs/create",
                headers={"X-API-Key": coordinator_key},
                files={"file": ("test.blend", f, "application/octet-stream")},
                data={"frame_start": 1, "frame_end": 10, "name": "Test Job"}
            )
        
        # Should succeed
        assert response.status_code == 200
        assert "job_id" in response.json()

    def test_unauthenticated_job_list_fails(self, client):
        """Test that listing jobs requires authentication."""
        response = client.get("/api/jobs")
        assert response.status_code == 401

    def test_authenticated_job_list_succeeds(self, client, coordinator):
        """Test that authenticated job list succeeds."""
        coordinator_key = coordinator.auth_manager.api_keys["coordinator"]
        
        response = client.get(
            "/api/jobs",
            headers={"X-API-Key": coordinator_key}
        )
        
        # Should succeed (even if empty)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestWorkerAuthentication:
    """Test worker endpoint authentication."""

    @pytest.fixture
    def coordinator(self):
        """Create a test coordinator server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_dir.mkdir(exist_ok=True)
            
            coordinator = CoordinatorServer(port=8422)
            coordinator.config_dir = config_dir
            coordinator.auth_manager = AuthManager(config_dir)
            # Re-setup routes with new auth_manager
            coordinator.app = FastAPI(title="WeRender Coordinator")
            coordinator._setup_routes()
            yield coordinator

    @pytest.fixture
    def client(self, coordinator):
        """Create a test client for the coordinator."""
        return TestClient(coordinator.app)

    def test_unauthenticated_task_request_fails(self, client):
        """Test that task requests require authentication."""
        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": "test_worker",
                "worker_name": "Test Worker",
                "cpu_cores": 4,
                "gpu_name": "None"
            }
        )
        assert response.status_code == 401

    def test_authenticated_task_request_succeeds(self, client, coordinator):
        """Test that authenticated task request succeeds."""
        worker_key = coordinator.auth_manager.api_keys["worker"]
        
        response = client.get(
            "/api/tasks/request",
            headers={"X-API-Key": worker_key},
            params={
                "worker_id": "test_worker",
                "worker_name": "Test Worker",
                "cpu_cores": 4,
                "gpu_name": "None"
            }
        )
        
        # Should succeed (204 if no tasks, 200 if tasks available)
        assert response.status_code in [200, 204]

    def test_coordinator_key_rejected_for_worker_endpoint(self, client, coordinator):
        """Test that coordinator key is rejected for worker endpoints."""
        coordinator_key = coordinator.auth_manager.api_keys["coordinator"]
        
        response = client.get(
            "/api/tasks/request",
            headers={"X-API-Key": coordinator_key},
            params={
                "worker_id": "test_worker",
                "worker_name": "Test Worker",
                "cpu_cores": 4,
                "gpu_name": "None"
            }
        )
        
        # Should get 403 Forbidden
        assert response.status_code == 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])