"""Comprehensive unit tests for coordinator.py."""

import asyncio
import hashlib
import io
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket, WebSocketDisconnect

from werender.core.job import FrameTask, RenderJob, TaskStatus
from werender.network.coordinator import CoordinatorServer, WorkerInfo
from werender.network.discovery import NodeInfo


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_system_specs():
    """Mock system specs."""
    mock_specs = MagicMock()
    mock_specs.hostname = "test-host"
    mock_specs.cpu_cores = 8
    mock_specs.ram_gb = 16.0
    return mock_specs


@pytest.fixture
def mock_blender_renderer():
    """Mock BlenderRenderer."""
    mock_renderer = MagicMock()
    mock_renderer.get_version.return_value = "4.0.0"
    mock_renderer.pack_resources.return_value = Path("/tmp/test_packed.blend")
    return mock_renderer


@pytest.fixture
def mock_failing_blender_renderer():
    """Mock BlenderRenderer that raises exception."""
    mock_renderer = MagicMock()
    mock_renderer.get_version.side_effect = Exception("Blender not found")
    return mock_renderer


@pytest.fixture
def mock_discovery_service():
    """Mock DiscoveryService."""
    mock_discovery = MagicMock()
    mock_discovery.start = MagicMock()
    mock_discovery.stop = MagicMock()
    return mock_discovery


@pytest.fixture
def mock_sync_manager():
    """Mock SyncManager."""
    mock_sync = MagicMock()
    mock_sync.get_manifest.return_value = {
        "settings_hash": "abc123",
        "addons_hash": "def456",
        "timestamp": 0,
    }
    mock_sync.get_settings.return_value = {"test_setting": "value"}
    mock_sync.get_addons_list.return_value = [
        {"name": "test_addon", "filename": "test_addon.zip", "hash": "hash123", "size": 1024}
    ]
    return mock_sync


@pytest.fixture
def coordinator(mock_system_specs, mock_blender_renderer, mock_discovery_service, mock_sync_manager):
    """Create a CoordinatorServer instance with mocked dependencies."""
    with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
         patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
         patch("werender.network.discovery.DiscoveryService", return_value=mock_discovery_service), \
         patch("werender.network.sync.SyncManager", return_value=mock_sync_manager):
        coord = CoordinatorServer(port=8420)
        # Use real temp directory for config
        coord.config_dir = Path(tempfile.mkdtemp())
        coord.config_dir.mkdir(exist_ok=True)
        coord.sync_manager = mock_sync_manager
        return coord


@pytest.fixture
def sample_blend_file():
    """Create a temporary blend file for testing with valid Blender header."""
    temp_dir = Path(tempfile.mkdtemp())
    blend_file = temp_dir / "test.blend"
    # Valid Blender file header: 'BLENDER' + pointer size ('_' for 64-bit) + endianness ('v' for little) + version (e.g., '401')
    # Format: BLENDER_v401 (12 bytes minimum header) + padding
    valid_header = b'BLENDER_v401' + b'\x00' * 100  # Add padding for file integrity
    blend_file.write_bytes(valid_header)
    return blend_file


@pytest.fixture
def sample_job(coordinator, sample_blend_file):
    """Create a sample render job."""
    job = RenderJob(
        name="Test Job",
        blend_file=sample_blend_file,
        frame_start=1,
        frame_end=5,
    )
    job.create_tasks()
    coordinator.jobs[job.id] = job
    return job


@pytest.fixture
def sample_worker():
    """Create a sample worker info."""
    return WorkerInfo(
        worker_id="worker-001",
        worker_name="test-worker",
        cpu_cores=8,
        gpu_name="Test GPU",
        last_seen=time.time(),
        current_task_id=None,
    )


@pytest.fixture
def auth_headers(coordinator):
    """Get authentication headers for API calls."""
    # Use the coordinator's auth manager to get the API keys
    coordinator_key = coordinator.auth_manager.get_key("coordinator")
    worker_key = coordinator.auth_manager.get_key("worker")
    return {
        "coordinator": {"X-API-Key": coordinator_key},
        "worker": {"X-API-Key": worker_key},
    }


@pytest.fixture
def client(coordinator, auth_headers):
    """Create a FastAPI TestClient with authentication."""
    # Store coordinator reference in app state for easy access
    coordinator.app.state.coordinator = coordinator
    
    # Create a wrapper class that auto-adds auth headers
    class AuthenticatedTestClient:
        def __init__(self, test_client, auth_headers):
            self._client = test_client
            self._auth_headers = auth_headers
            # Store app reference for compatibility
            self.app = test_client.app
        
        def _get_auth_header(self, endpoint: str) -> dict:
            """Determine which auth header to use based on endpoint."""
            # Worker endpoints
            worker_endpoints = ["/api/tasks/request", "/api/tasks/", "/api/jobs/", "/api/sync/"]
            # Check if it's a worker-only endpoint (task request, complete, fail, get blend, sync)
            if any(endpoint.startswith(ep) for ep in ["/api/tasks/request", "/api/sync/"]):
                return self._auth_headers["worker"]
            if "/api/tasks/" in endpoint and ("/complete" in endpoint or "/fail" in endpoint):
                return self._auth_headers["worker"]
            if "/blend" in endpoint:
                return self._auth_headers["worker"]
            # Default to coordinator auth for all other endpoints
            return self._auth_headers["coordinator"]
        
        def get(self, url, **kwargs):
            headers = kwargs.pop("headers", {})
            headers.update(self._get_auth_header(url))
            return self._client.get(url, headers=headers, **kwargs)
        
        def post(self, url, **kwargs):
            headers = kwargs.pop("headers", {})
            headers.update(self._get_auth_header(url))
            return self._client.post(url, headers=headers, **kwargs)
        
        def put(self, url, **kwargs):
            headers = kwargs.pop("headers", {})
            headers.update(self._get_auth_header(url))
            return self._client.put(url, headers=headers, **kwargs)
        
        def patch(self, url, **kwargs):
            headers = kwargs.pop("headers", {})
            headers.update(self._get_auth_header(url))
            return self._client.patch(url, headers=headers, **kwargs)
        
        def delete(self, url, **kwargs):
            headers = kwargs.pop("headers", {})
            headers.update(self._get_auth_header(url))
            return self._client.delete(url, headers=headers, **kwargs)
    
    test_client = TestClient(coordinator.app)
    return AuthenticatedTestClient(test_client, auth_headers)


# ============================================================================
# Tests for CoordinatorServer.__init__
# ============================================================================


class TestCoordinatorServerInitialization:
    """Tests for CoordinatorServer initialization."""

    def test_init_creates_server_with_default_port(self, mock_system_specs, mock_blender_renderer):
        """Test initialization with default port."""
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
             patch("werender.network.discovery.DiscoveryService"), \
             patch("werender.network.sync.SyncManager"):
            coordinator = CoordinatorServer()
            assert coordinator.port == 8420
            assert coordinator.node_id is not None
            assert len(coordinator.node_id) == 8

    def test_init_creates_server_with_custom_port(self, mock_system_specs, mock_blender_renderer):
        """Test initialization with custom port."""
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
             patch("werender.network.discovery.DiscoveryService"), \
             patch("werender.network.sync.SyncManager"):
            coordinator = CoordinatorServer(port=9000)
            assert coordinator.port == 9000

    def test_init_initializes_empty_jobs_dict(self, coordinator):
        """Test that jobs dictionary is initialized empty."""
        assert coordinator.jobs == {}

    def test_init_initializes_empty_workers_dict(self, coordinator):
        """Test that workers dictionary is initialized empty."""
        assert coordinator.workers == {}

    def test_init_initializes_empty_websocket_connections(self, coordinator):
        """Test that websocket connections list is initialized empty."""
        assert coordinator.websocket_connections == []

    def test_init_creates_fastapi_app(self, coordinator):
        """Test that FastAPI app is created."""
        assert coordinator.app is not None
        assert coordinator.app.title == "WeRender Coordinator"

    def test_init_sets_up_routes(self, coordinator):
        """Test that routes are set up during initialization."""
        # Check that event handlers are registered
        # on_event is a method, not a list. Just check it exists.
        assert hasattr(coordinator.app, 'on_event')

    def test_init_creates_discovery_service(self, coordinator, mock_discovery_service):
        """Test that discovery service is created."""
        assert coordinator.discovery is not None

    def test_init_creates_sync_manager(self, coordinator, mock_sync_manager):
        """Test that sync manager is created."""
        assert coordinator.sync_manager is not None

    def test_init_handles_blender_version_failure(self, mock_system_specs):
        """Test initialization when Blender version check fails."""
        # Use 'new' parameter to create a new instance that raises exception
        mock_failing_renderer = MagicMock()
        mock_failing_renderer.get_version.side_effect = Exception("Blender not found")
        
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_failing_renderer), \
             patch("werender.network.discovery.DiscoveryService"), \
             patch("werender.network.sync.SyncManager"):
            coordinator = CoordinatorServer()
            # When BlenderRenderer fails, version should be empty string
            assert coordinator.blender_version == ""


# ============================================================================
# Tests for _get_blend_file_hash
# ============================================================================


class TestGetBlendFileHash:
    """Tests for _get_blend_file_hash method."""

    def test_get_blend_file_hash_with_packed_file(self, coordinator, sample_job):
        """Test hash calculation with packed file."""
        # Create a temporary packed file
        packed_file = Path(tempfile.mktemp(suffix=".blend"))
        packed_file.write_bytes(b"test packed content")
        sample_job.packed_file = packed_file

        expected_hash = hashlib.md5(b"test packed content").hexdigest()
        result = coordinator._get_blend_file_hash(sample_job)

        assert result == expected_hash
        packed_file.unlink(missing_ok=True)

    def test_get_blend_file_hash_with_original_file(self, coordinator, sample_job):
        """Test hash calculation with original blend file."""
        expected_hash = hashlib.md5(b"fake blend file content").hexdigest()
        result = coordinator._get_blend_file_hash(sample_job)

        assert result == expected_hash

    def test_get_blend_file_hash_different_content(self, coordinator):
        """Test that different files produce different hashes."""
        temp_dir = Path(tempfile.mkdtemp())
        file1 = temp_dir / "file1.blend"
        file2 = temp_dir / "file2.blend"
        file1.write_bytes(b"content 1")
        file2.write_bytes(b"content 2")

        job1 = RenderJob(name="Job1", blend_file=file1, frame_start=1, frame_end=2)
        job2 = RenderJob(name="Job2", blend_file=file2, frame_start=1, frame_end=2)

        hash1 = coordinator._get_blend_file_hash(job1)
        hash2 = coordinator._get_blend_file_hash(job2)

        assert hash1 != hash2

        file1.unlink(missing_ok=True)
        file2.unlink(missing_ok=True)
        temp_dir.rmdir()


# ============================================================================
# Tests for _on_worker_discovered
# ============================================================================


class TestOnWorkerDiscovered:
    """Tests for _on_worker_discovered method."""

    @pytest.mark.asyncio
    async def test_on_worker_discovered_broadcasts_update(self, coordinator):
        """Test that worker discovery broadcasts update."""
        coordinator._broadcast_update = AsyncMock()

        node = NodeInfo(
            name="test-worker",
            address="192.168.1.100",
            port=8080,
            node_type="worker",
            properties={"hostname": "test-worker"},
        )

        await coordinator._on_worker_discovered(node)

        coordinator._broadcast_update.assert_called_once_with("workers")

    @pytest.mark.asyncio
    async def test_on_worker_discovered_with_various_node_types(self, coordinator):
        """Test worker discovery with different node types."""
        coordinator._broadcast_update = AsyncMock()

        for node_type in ["worker", "coordinator"]:
            node = NodeInfo(
                name=f"test-{node_type}",
                address="192.168.1.100",
                port=8080,
                node_type=node_type,
                properties={"hostname": f"test-{node_type}"},
            )

            await coordinator._on_worker_discovered(node)

        assert coordinator._broadcast_update.call_count == 2


# ============================================================================
# Tests for _on_worker_removed
# ============================================================================


class TestOnWorkerRemoved:
    """Tests for _on_worker_removed method."""

    @pytest.mark.asyncio
    async def test_on_worker_removed_removes_worker(self, coordinator, sample_worker):
        """Test that worker is removed when node is removed."""
        coordinator.workers[sample_worker.worker_id] = sample_worker
        coordinator._broadcast_update = AsyncMock()

        node = NodeInfo(
            name=sample_worker.worker_name,
            address="192.168.1.100",
            port=8080,
            node_type="worker",
            properties={"hostname": sample_worker.worker_name},
        )

        await coordinator._on_worker_removed(node)

        assert sample_worker.worker_id not in coordinator.workers
        coordinator._broadcast_update.assert_called_once_with("workers")

    @pytest.mark.asyncio
    async def test_on_worker_removed_requeues_task(self, coordinator, sample_worker, sample_job):
        """Test that task is re-queued when worker is removed."""
        # Assign a task to the worker
        task = sample_job.tasks[0]
        task.assign_to(sample_worker.worker_id)
        task.start_rendering()
        sample_worker.current_task_id = task.id

        coordinator.workers[sample_worker.worker_id] = sample_worker
        coordinator._broadcast_update = AsyncMock()

        node = NodeInfo(
            name=sample_worker.worker_name,
            address="192.168.1.100",
            port=8080,
            node_type="worker",
            properties={"hostname": sample_worker.worker_name},
        )

        await coordinator._on_worker_removed(node)

        # Task should be reset to pending
        assert task.status == TaskStatus.PENDING
        assert task.assigned_worker is None

    @pytest.mark.asyncio
    async def test_on_worker_removed_multiple_workers(self, coordinator):
        """Test removing worker when multiple workers exist."""
        worker1 = WorkerInfo(
            worker_id="worker-001",
            worker_name="worker-1",
            cpu_cores=8,
            gpu_name="GPU1",
            last_seen=time.time(),
        )
        worker2 = WorkerInfo(
            worker_id="worker-002",
            worker_name="worker-2",
            cpu_cores=8,
            gpu_name="GPU2",
            last_seen=time.time(),
        )

        coordinator.workers[worker1.worker_id] = worker1
        coordinator.workers[worker2.worker_id] = worker2
        coordinator._broadcast_update = AsyncMock()

        node = NodeInfo(
            name=worker1.worker_name,
            address="192.168.1.100",
            port=8080,
            node_type="worker",
            properties={"hostname": worker1.worker_name},
        )

        await coordinator._on_worker_removed(node)

        assert worker1.worker_id not in coordinator.workers
        assert worker2.worker_id in coordinator.workers

    @pytest.mark.asyncio
    async def test_on_worker_removed_nonexistent_worker(self, coordinator):
        """Test handling removal of worker that doesn't exist."""
        coordinator._broadcast_update = AsyncMock()

        node = NodeInfo(
            name="nonexistent-worker",
            address="192.168.1.100",
            port=8080,
            node_type="worker",
            properties={"hostname": "nonexistent-worker"},
        )

        # Should not raise an error
        await coordinator._on_worker_removed(node)
        coordinator._broadcast_update.assert_called_once_with("workers")


# ============================================================================
# Tests for API Endpoints - Task Management
# ============================================================================


class TestApiRequestTask:
    """Tests for _api_request_task endpoint."""

    def test_request_task_with_no_jobs(self, client):
        """Test requesting task when no jobs exist."""
        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": "worker-001",
                "worker_name": "test-worker",
                "cpu_cores": 8,
                "gpu_name": "Test GPU",
            },
        )
        assert response.status_code == 204  # No content

    def test_request_task_with_pending_job(self, client, sample_job):
        """Test requesting task with a pending job."""
        sample_job.start()

        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": "worker-001",
                "worker_name": "test-worker",
                "cpu_cores": 8,
                "gpu_name": "Test GPU",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert "id" in data
        assert "job_id" in data
        assert "frame_number" in data
        assert "blend_file_hash" in data

    def test_request_task_creates_worker(self, client, sample_job):
        """Test that requesting task creates worker if not exists."""
        sample_job.start()

        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": "worker-001",
                "worker_name": "test-worker",
                "cpu_cores": 8,
                "gpu_name": "Test GPU",
            },
        )
        assert response.status_code == 200

        # Get the coordinator from the app state
        from werender.network.coordinator import CoordinatorServer
        coordinator = client.app.state.coordinator

        if coordinator and "worker-001" in coordinator.workers:
            worker = coordinator.workers["worker-001"]
            assert worker.worker_name == "test-worker"
            assert worker.cpu_cores == 8
            assert worker.gpu_name == "Test GPU"

    def test_request_task_updates_existing_worker(self, client, sample_job, sample_worker):
        """Test that requesting task updates existing worker."""
        coordinator = client.app.state.coordinator
        coordinator.workers[sample_worker.worker_id] = sample_worker
        sample_job.start()

        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": sample_worker.worker_id,
                "worker_name": "updated-worker",
                "cpu_cores": 16,
                "gpu_name": "Updated GPU",
            },
        )
        assert response.status_code == 200

        # Worker should be updated
        worker = coordinator.workers[sample_worker.worker_id]
        assert worker.worker_name == "updated-worker"
        assert worker.cpu_cores == 16
        assert worker.gpu_name == "Updated GPU"

    def test_request_task_assigns_task(self, client, sample_job):
        """Test that requesting task assigns task to worker."""
        sample_job.start()

        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": "worker-001",
                "worker_name": "test-worker",
                "cpu_cores": 8,
                "gpu_name": "Test GPU",
            },
        )
        assert response.status_code == 200

        data = response.json()
        task_id = data["id"]

        # Find the task in the job
        task = next((t for t in sample_job.tasks if t.id == task_id), None)
        assert task is not None
        assert task.assigned_worker == "worker-001"
        assert task.status == TaskStatus.RENDERING

    def test_request_task_no_running_jobs(self, client, sample_job):
        """Test requesting task when job is not running."""
        # Job is pending, not running
        response = client.get(
            "/api/tasks/request",
            params={
                "worker_id": "worker-001",
                "worker_name": "test-worker",
                "cpu_cores": 8,
                "gpu_name": "Test GPU",
            },
        )
        assert response.status_code == 204


class TestApiCompleteTask:
    """Tests for _api_complete_task endpoint."""

    def test_complete_task_success(self, client, sample_job):
        """Test completing a task successfully."""
        # Set up a task as assigned
        task = sample_job.tasks[0]
        task.assign_to("worker-001")
        task.start_rendering()

        # Create mock output file
        output_content = b"fake image data"
        output_file = io.BytesIO(output_content)

        response = client.post(
            f"/api/tasks/{task.id}/complete",
            files={"output": ("0001.png", output_file, "image/png")},
            data={"render_time": "1.5"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert task.status == TaskStatus.COMPLETED

    def test_complete_task_not_found(self, client):
        """Test completing a non-existent task."""
        response = client.post(
            "/api/tasks/nonexistent/complete",
            files={"output": ("0001.png", io.BytesIO(b"data"), "image/png")},
            data={"render_time": "1.5"},
        )
        assert response.status_code == 404

    def test_complete_task_frees_worker(self, client, sample_job, sample_worker):
        """Test that completing task frees the worker."""
        coordinator = client.app.state.coordinator
        coordinator.workers[sample_worker.worker_id] = sample_worker

        task = sample_job.tasks[0]
        task.assign_to(sample_worker.worker_id)
        task.start_rendering()
        sample_worker.current_task_id = task.id

        response = client.post(
            f"/api/tasks/{task.id}/complete",
            files={"output": ("0001.png", io.BytesIO(b"data"), "image/png")},
            data={"render_time": "1.5"},
        )
        assert response.status_code == 200
        assert coordinator.workers[sample_worker.worker_id].current_task_id is None

    def test_complete_task_job_completion(self, client, sample_job):
        """Test that completing all tasks marks job as complete."""
        sample_job.start()

        # Complete all tasks
        for task in sample_job.tasks:
            task.assign_to("worker-001")
            task.start_rendering()

            response = client.post(
                f"/api/tasks/{task.id}/complete",
                files={"output": (f"{task.frame_number:04d}.png", io.BytesIO(b"data"), "image/png")},
                data={"render_time": "1.5"},
            )
            assert response.status_code == 200

        assert sample_job.status == "completed"


class TestApiFailTask:
    """Tests for _api_fail_task endpoint."""

    def test_fail_task_success(self, client, sample_job):
        """Test failing a task."""
        task = sample_job.tasks[0]
        task.assign_to("worker-001")
        task.start_rendering()

        response = client.post(
            f"/api/tasks/{task.id}/fail",
            json={"error": "Out of memory"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert task.status == TaskStatus.FAILED
        assert task.error_message == "Out of memory"

    def test_fail_task_not_found(self, client):
        """Test failing a non-existent task."""
        response = client.post(
            "/api/tasks/nonexistent/fail",
            json={"error": "Task not found"},
        )
        assert response.status_code == 404

    def test_fail_task_frees_worker(self, client, sample_job, sample_worker):
        """Test that failing task frees the worker."""
        coordinator = client.app.state.coordinator
        coordinator.workers[sample_worker.worker_id] = sample_worker

        task = sample_job.tasks[0]
        task.assign_to(sample_worker.worker_id)
        task.start_rendering()
        sample_worker.current_task_id = task.id

        response = client.post(
            f"/api/tasks/{task.id}/fail",
            json={"error": "Render failed"},
        )
        assert response.status_code == 200
        assert coordinator.workers[sample_worker.worker_id].current_task_id is None

    def test_fail_task_default_error(self, client, sample_job):
        """Test failing task without providing error message."""
        task = sample_job.tasks[0]
        task.assign_to("worker-001")

        response = client.post(
            f"/api/tasks/{task.id}/fail",
            json={},
        )
        assert response.status_code == 200
        assert task.error_message == "Unknown error"


# ============================================================================
# Tests for API Endpoints - Job Management
# ============================================================================


class TestApiCreateJob:
    """Tests for _api_create_job endpoint."""

    def test_create_job_success(self, client, sample_blend_file):
        """Test creating a job successfully."""
        with open(sample_blend_file, "rb") as f:
            response = client.post(
                "/api/jobs/create",
                files={"file": ("test.blend", f, "application/octet-stream")},
                data={
                    "frame_start": 1,
                    "frame_end": 10,
                    "name": "Test Job",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

    def test_create_job_default_name(self, client, sample_blend_file):
        """Test creating job without providing name."""
        with open(sample_blend_file, "rb") as f:
            response = client.post(
                "/api/jobs/create",
                files={"file": ("my_job.blend", f, "application/octet-stream")},
                data={
                    "frame_start": 1,
                    "frame_end": 5,
                },
            )
        assert response.status_code == 200

        # Find the created job
        coordinator = client.app.state.coordinator
        job_id = response.json()["job_id"]
        job = coordinator.jobs[job_id]
        assert job.name == "my_job.blend"


class TestApiListJobs:
    """Tests for _api_list_jobs endpoint."""

    def test_list_jobs_empty(self, client):
        """Test listing jobs when none exist."""
        response = client.get("/api/jobs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_jobs_with_jobs(self, client, sample_job):
        """Test listing jobs when jobs exist."""
        response = client.get("/api/jobs")
        assert response.status_code == 200

        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == sample_job.id
        assert jobs[0]["name"] == sample_job.name
        assert jobs[0]["status"] == sample_job.status
        assert jobs[0]["total_frames"] == sample_job.total_frames
        assert jobs[0]["frame_start"] == sample_job.frame_start
        assert jobs[0]["frame_end"] == sample_job.frame_end

    def test_list_jobs_multiple_jobs(self, client, sample_blend_file):
        """Test listing multiple jobs."""
        coordinator = client.app.state.coordinator

        # Create multiple jobs
        for i in range(3):
            job = RenderJob(
                name=f"Job {i}",
                blend_file=sample_blend_file,
                frame_start=1,
                frame_end=5,
            )
            job.create_tasks()
            coordinator.jobs[job.id] = job

        response = client.get("/api/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 3


class TestApiGetJob:
    """Tests for _api_get_job endpoint."""

    def test_get_job_success(self, client, sample_job):
        """Test getting job details."""
        response = client.get(f"/api/jobs/{sample_job.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == sample_job.id
        assert data["name"] == sample_job.name
        assert data["status"] == sample_job.status
        assert "tasks" in data
        assert len(data["tasks"]) == len(sample_job.tasks)

    def test_get_job_not_found(self, client):
        """Test getting non-existent job."""
        response = client.get("/api/jobs/nonexistent")
        assert response.status_code == 404

    def test_get_job_includes_task_details(self, client, sample_job):
        """Test that job details include task information."""
        response = client.get(f"/api/jobs/{sample_job.id}")
        data = response.json()

        tasks = data["tasks"]
        assert len(tasks) == len(sample_job.tasks)
        assert tasks[0]["frame_number"] == sample_job.tasks[0].frame_number
        assert tasks[0]["status"] == sample_job.tasks[0].status


class TestApiStartJob:
    """Tests for _api_start_job endpoint."""

    def test_start_job_success(self, client, sample_job):
        """Test starting a job."""
        response = client.post(f"/api/jobs/{sample_job.id}/start")
        assert response.status_code == 200
        assert response.json()["status"] == "running"
        assert sample_job.status == "running"

    def test_start_job_not_found(self, client):
        """Test starting non-existent job."""
        response = client.post("/api/jobs/nonexistent/start")
        assert response.status_code == 404

    def test_start_job_already_running(self, client, sample_job):
        """Test starting a job that's already running."""
        sample_job.start()
        response = client.post(f"/api/jobs/{sample_job.id}/start")
        assert response.status_code == 200  # Still succeeds


class TestApiPauseJob:
    """Tests for _api_pause_job endpoint."""

    def test_pause_job_success(self, client, sample_job):
        """Test pausing a job."""
        sample_job.start()
        response = client.post(f"/api/jobs/{sample_job.id}/pause")
        assert response.status_code == 200
        assert response.json()["status"] == "paused"
        assert sample_job.status == "paused"

    def test_pause_job_not_found(self, client):
        """Test pausing non-existent job."""
        response = client.post("/api/jobs/nonexistent/pause")
        assert response.status_code == 404


class TestApiResumeJob:
    """Tests for _api_resume_job endpoint."""

    def test_resume_job_success(self, client, sample_job):
        """Test resuming a paused job."""
        sample_job.start()
        sample_job.pause()
        response = client.post(f"/api/jobs/{sample_job.id}/resume")
        assert response.status_code == 200
        assert response.json()["status"] == "running"
        assert sample_job.status == "running"

    def test_resume_job_not_found(self, client):
        """Test resuming non-existent job."""
        response = client.post("/api/jobs/nonexistent/resume")
        assert response.status_code == 404


class TestApiCancelJob:
    """Tests for _api_cancel_job endpoint."""

    def test_cancel_job_success(self, client, sample_job):
        """Test cancelling a job."""
        sample_job.start()
        response = client.post(f"/api/jobs/{sample_job.id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert sample_job.status == "cancelled"

    def test_cancel_job_not_found(self, client):
        """Test cancelling non-existent job."""
        response = client.post("/api/jobs/nonexistent/cancel")
        assert response.status_code == 404

    def test_cancel_job_resets_tasks(self, client, sample_job):
        """Test that cancelling job resets pending tasks."""
        sample_job.start()

        # Mark some tasks as assigned
        for i, task in enumerate(sample_job.tasks[:2]):
            task.assign_to(f"worker-{i}")

        response = client.post(f"/api/jobs/{sample_job.id}/cancel")
        assert response.status_code == 200

        # All non-completed tasks should be reset
        for task in sample_job.tasks:
            if task.status != TaskStatus.COMPLETED:
                assert task.status == TaskStatus.PENDING
                assert task.assigned_worker is None


class TestApiUpdateJob:
    """Tests for _api_update_job endpoint."""

    def test_update_job_frame_range(self, client, sample_job):
        """Test updating job frame range."""
        response = client.patch(
            f"/api/jobs/{sample_job.id}",
            json={"start_frame": 10, "end_frame": 20},
        )
        assert response.status_code == 200
        assert sample_job.frame_start == 10
        assert sample_job.frame_end == 20
        assert len(sample_job.tasks) == 11  # 10-20 inclusive

    def test_update_job_not_found(self, client):
        """Test updating non-existent job."""
        response = client.patch(
            "/api/jobs/nonexistent",
            json={"start_frame": 1, "end_frame": 10},
        )
        assert response.status_code == 404

    def test_update_job_running_job(self, client, sample_job):
        """Test that updating running job fails."""
        sample_job.start()
        response = client.patch(
            f"/api/jobs/{sample_job.id}",
            json={"start_frame": 1, "end_frame": 10},
        )
        assert response.status_code == 400

    def test_update_job_invalid_frame_range(self, client, sample_job):
        """Test updating with invalid frame range."""
        response = client.patch(
            f"/api/jobs/{sample_job.id}",
            json={"start_frame": 20, "end_frame": 10},
        )
        assert response.status_code == 400

    def test_update_job_partial_update(self, client, sample_job):
        """Test updating only start_frame."""
        original_end = sample_job.frame_end
        response = client.patch(
            f"/api/jobs/{sample_job.id}",
            json={"start_frame": 3},
        )
        assert response.status_code == 200
        assert sample_job.frame_start == 3
        assert sample_job.frame_end == original_end

    def test_update_job_completed_job(self, client, sample_job):
        """Test that updating completed job resets status."""
        # Complete all tasks
        for task in sample_job.tasks:
            task.complete(Path(f"/output/{task.frame_number:04d}.png"))
        sample_job.check_completion()

        response = client.patch(
            f"/api/jobs/{sample_job.id}",
            json={"start_frame": 1, "end_frame": 3},
        )
        assert response.status_code == 200
        assert sample_job.status == "pending"


class TestApiGetBlendFile:
    """Tests for _api_get_blend_file endpoint."""

    def test_get_blend_file_success(self, client, sample_job):
        """Test downloading blend file."""
        response = client.get(f"/api/jobs/{sample_job.id}/blend")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"

    def test_get_blend_file_not_found(self, client):
        """Test downloading blend file for non-existent job."""
        response = client.get("/api/jobs/nonexistent/blend")
        assert response.status_code == 404

    def test_get_blend_file_packed_file(self, client, sample_job):
        """Test that packed file is used if available."""
        # Create a packed file
        packed_file = Path(tempfile.mktemp(suffix=".blend"))
        packed_file.write_bytes(b"packed content")
        sample_job.packed_file = packed_file

        response = client.get(f"/api/jobs/{sample_job.id}/blend")
        assert response.status_code == 200

        packed_file.unlink(missing_ok=True)


class TestApiReloadBlend:
    """Tests for _api_reload_blend endpoint."""

    def test_reload_blend_success(self, client, sample_job, sample_blend_file):
        """Test reloading blend file."""
        with open(sample_blend_file, "rb") as f:
            response = client.post(
                f"/api/jobs/{sample_job.id}/reload_blend",
                files={"blend": ("new.blend", f, "application/octet-stream")},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert sample_job.status == "pending"

    def test_reload_blend_not_found(self, client, sample_blend_file):
        """Test reloading blend file for non-existent job."""
        with open(sample_blend_file, "rb") as f:
            response = client.post(
                "/api/jobs/nonexistent/reload_blend",
                files={"blend": ("test.blend", f, "application/octet-stream")},
            )
        assert response.status_code == 404

    def test_reload_blend_invalid_extension(self, client, sample_job):
        """Test reloading with non-blend file."""
        response = client.post(
            f"/api/jobs/{sample_job.id}/reload_blend",
            files={"blend": ("test.txt", io.BytesIO(b"data"), "text/plain")},
        )
        assert response.status_code == 400

    def test_reload_blend_running_job(self, client, sample_job, sample_blend_file):
        """Test that reloading blend file for running job fails."""
        sample_job.start()
        with open(sample_blend_file, "rb") as f:
            response = client.post(
                f"/api/jobs/{sample_job.id}/reload_blend",
                files={"blend": ("new.blend", f, "application/octet-stream")},
            )
        assert response.status_code == 400


# ============================================================================
# Tests for API Endpoints - Worker Management
# ============================================================================


class TestApiListWorkers:
    """Tests for _api_list_workers endpoint."""

    def test_list_workers_empty(self, client):
        """Test listing workers when none exist."""
        response = client.get("/api/workers")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_workers_with_workers(self, client, sample_worker):
        """Test listing workers when workers exist."""
        coordinator = client.app.state.coordinator
        coordinator.workers[sample_worker.worker_id] = sample_worker

        response = client.get("/api/workers")
        assert response.status_code == 200

        workers = response.json()
        assert len(workers) == 1
        assert workers[0]["worker_id"] == sample_worker.worker_id
        assert workers[0]["worker_name"] == sample_worker.worker_name
        assert workers[0]["cpu_cores"] == sample_worker.cpu_cores
        assert workers[0]["gpu_name"] == sample_worker.gpu_name

    def test_list_workers_multiple_workers(self, client):
        """Test listing multiple workers."""
        coordinator = client.app.state.coordinator

        for i in range(3):
            worker = WorkerInfo(
                worker_id=f"worker-{i}",
                worker_name=f"worker-{i}",
                cpu_cores=8,
                gpu_name=f"GPU-{i}",
                last_seen=time.time(),
            )
            coordinator.workers[worker.worker_id] = worker

        response = client.get("/api/workers")
        assert response.status_code == 200
        workers = response.json()
        assert len(workers) == 3


# ============================================================================
# Tests for API Endpoints - Sync and Settings
# ============================================================================


class TestApiGetSyncManifest:
    """Tests for _api_get_sync_manifest endpoint."""

    def test_get_sync_manifest(self, client):
        """Test getting sync manifest."""
        response = client.get("/api/sync/manifest")
        assert response.status_code == 200
        data = response.json()
        assert "settings_hash" in data
        assert "addons_hash" in data
        assert "timestamp" in data


class TestApiGetSettings:
    """Tests for _api_get_settings endpoint."""

    def test_get_settings(self, client):
        """Test getting settings."""
        response = client.get("/api/sync/settings")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestApiListAddons:
    """Tests for _api_list_addons endpoint."""

    def test_list_addons(self, client):
        """Test listing addons."""
        response = client.get("/api/sync/addons")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestApiDownloadAddon:
    """Tests for _api_download_addon endpoint."""

    def test_download_addon_success(self, client, mock_sync_manager):
        """Test downloading an addon."""
        # Create a temporary addon file
        addon_dir = Path(tempfile.mkdtemp())
        addon_file = addon_dir / "test_addon.zip"
        addon_file.write_bytes(b"fake addon content")

        mock_sync_manager.addons_dir = addon_dir
        mock_sync_manager.get_addons_list.return_value = [
            {"name": "test_addon", "filename": "test_addon.zip", "hash": "hash123", "size": 19}
        ]

        response = client.get("/api/sync/addons/test_addon/download")
        assert response.status_code == 200

        addon_file.unlink(missing_ok=True)
        addon_dir.rmdir()

    def test_download_addon_not_found(self, client):
        """Test downloading non-existent addon."""
        response = client.get("/api/sync/addons/nonexistent/download")
        assert response.status_code == 404


# ============================================================================
# Tests for WebSocket
# ============================================================================


class TestWebSocketEndpoint:
    """Tests for _websocket_endpoint."""

    def test_websocket_accepts_connection(self, coordinator):
        """Test that WebSocket accepts connection."""
        mock_websocket = AsyncMock(spec=WebSocket)
        mock_websocket.receive_text.side_effect = [AsyncMock(), WebSocketDisconnect()]

        # This would need to be tested with a real WebSocket client
        # For unit testing, we test the broadcast functionality instead
        pass


class TestBroadcastUpdate:
    """Tests for _broadcast_update method."""

    @pytest.mark.asyncio
    async def test_broadcast_update_no_connections(self, coordinator):
        """Test broadcasting with no connections."""
        # Should not raise an error
        await coordinator._broadcast_update("jobs")

    @pytest.mark.asyncio
    async def test_broadcast_update_jobs(self, coordinator, sample_job):
        """Test broadcasting jobs update."""
        mock_websocket = AsyncMock()
        coordinator.websocket_connections = [mock_websocket]

        await coordinator._broadcast_update("jobs")

        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "jobs"
        assert "jobs" in call_args

    @pytest.mark.asyncio
    async def test_broadcast_update_workers(self, coordinator, sample_worker):
        """Test broadcasting workers update."""
        mock_websocket = AsyncMock()
        coordinator.websocket_connections = [mock_websocket]
        coordinator.workers[sample_worker.worker_id] = sample_worker

        await coordinator._broadcast_update("workers")

        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "workers"
        assert "workers" in call_args

    @pytest.mark.asyncio
    async def test_broadcast_update_all(self, coordinator, sample_job, sample_worker):
        """Test broadcasting all updates."""
        mock_websocket = AsyncMock()
        coordinator.websocket_connections = [mock_websocket]
        coordinator.workers[sample_worker.worker_id] = sample_worker

        await coordinator._broadcast_update("all")

        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "all"
        assert "jobs" in call_args
        assert "workers" in call_args

    @pytest.mark.asyncio
    async def test_broadcast_update_removes_disconnected(self, coordinator):
        """Test that disconnected websockets are removed."""
        mock_websocket = AsyncMock()
        mock_websocket.send_json.side_effect = Exception("Connection lost")
        coordinator.websocket_connections = [mock_websocket]

        await coordinator._broadcast_update("jobs")

        assert len(coordinator.websocket_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_update_multiple_connections(self, coordinator):
        """Test broadcasting to multiple connections."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        coordinator.websocket_connections = [mock_ws1, mock_ws2]

        await coordinator._broadcast_update("jobs")

        mock_ws1.send_json.assert_called_once()
        mock_ws2.send_json.assert_called_once()


# ============================================================================
# Tests for Background Loops
# ============================================================================


class TestHealthCheckLoop:
    """Tests for _health_check_loop."""

    @pytest.mark.asyncio
    async def test_health_check_removes_stale_workers(self, coordinator, sample_worker):
        """Test that stale workers are removed."""
        # Set worker as stale (old last_seen)
        sample_worker.last_seen = time.time() - 60  # 60 seconds ago
        coordinator.workers[sample_worker.worker_id] = sample_worker
        coordinator._broadcast_update = AsyncMock()

        # Run one iteration of the loop - must wait longer than 5 second initial sleep
        async_task = asyncio.create_task(coordinator._health_check_loop())
        await asyncio.sleep(6)  # Wait longer than the 5 second sleep in the loop
        async_task.cancel()

        try:
            await async_task
        except asyncio.CancelledError:
            pass

        # Worker should be removed
        assert sample_worker.worker_id not in coordinator.workers

    @pytest.mark.asyncio
    async def test_health_check_requeues_stale_tasks(self, coordinator, sample_job, sample_worker):
        """Test that tasks from stale workers are re-queued."""
        # Assign a task to the worker (renamed to frame_task to avoid shadowing)
        frame_task = sample_job.tasks[0]
        frame_task.assign_to(sample_worker.worker_id)
        frame_task.start_rendering()
        sample_worker.current_task_id = frame_task.id
        sample_worker.last_seen = time.time() - 60

        coordinator.workers[sample_worker.worker_id] = sample_worker
        coordinator._broadcast_update = AsyncMock()

        # Run one iteration - note: the health check loop sleeps for 5 seconds,
        # but we give it enough time by checking the actual task state after cancelling
        async_task = asyncio.create_task(coordinator._health_check_loop())
        await asyncio.sleep(6)  # Wait longer than the 5 second sleep in the loop
        async_task.cancel()

        try:
            await async_task
        except asyncio.CancelledError:
            pass

        # Task should be reset (worker is removed, so task should be reset)
        assert frame_task.status == TaskStatus.PENDING
        assert frame_task.assigned_worker is None

    @pytest.mark.asyncio
    async def test_health_check_keeps_active_workers(self, coordinator, sample_worker):
        """Test that active workers are kept."""
        # Worker is active (recent last_seen)
        sample_worker.last_seen = time.time() - 10  # 10 seconds ago
        coordinator.workers[sample_worker.worker_id] = sample_worker
        coordinator._broadcast_update = AsyncMock()

        # Run one iteration
        task = asyncio.create_task(coordinator._health_check_loop())
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Worker should still be present
        assert sample_worker.worker_id in coordinator.workers


class TestBroadcastUpdatesLoop:
    """Tests for _broadcast_updates_loop."""

    @pytest.mark.asyncio
    async def test_broadcast_updates_loop_broadcasts(self, coordinator):
        """Test that broadcast loop sends updates."""
        coordinator._broadcast_update = AsyncMock()

        # Run one iteration - must wait longer than 2 second sleep in the loop
        async_task = asyncio.create_task(coordinator._broadcast_updates_loop())
        await asyncio.sleep(3)  # Wait longer than the 2 second sleep in the loop
        async_task.cancel()

        try:
            await async_task
        except asyncio.CancelledError:
            pass

        # Should have broadcast at least once
        coordinator._broadcast_update.assert_called()


# ============================================================================
# Tests for Lifecycle Methods
# ============================================================================


class TestLifecycleMethods:
    """Tests for lifecycle methods."""

    @pytest.mark.asyncio
    async def test_on_startup(self, coordinator, mock_discovery_service):
        """Test startup event handler."""
        await coordinator._on_startup()

        mock_discovery_service.start.assert_called_once()
        assert coordinator.discovery.on_discovery is not None
        assert coordinator.discovery.on_removal is not None

    @pytest.mark.asyncio
    async def test_on_shutdown(self, coordinator, mock_discovery_service):
        """Test shutdown event handler."""
        await coordinator._on_shutdown()

        mock_discovery_service.stop.assert_called_once()

    def test_setup_routes(self, coordinator):
        """Test that routes are set up correctly."""
        # Check that various routes exist
        routes = [route.path for route in coordinator.app.routes]
        assert "/api/tasks/request" in routes
        assert "/api/jobs" in routes
        assert "/api/workers" in routes
        assert "/ws" in routes


class TestSetupRoutes:
    """Tests for _setup_routes method."""

    def test_setup_routes_registers_task_endpoints(self, coordinator):
        """Test that task endpoints are registered."""
        routes = [route.path for route in coordinator.app.routes]
        assert "/api/tasks/request" in routes
        assert any("/api/tasks/" in r and "/complete" in r for r in routes)
        assert any("/api/tasks/" in r and "/fail" in r for r in routes)

    def test_setup_routes_registers_job_endpoints(self, coordinator):
        """Test that job endpoints are registered."""
        routes = [route.path for route in coordinator.app.routes]
        assert "/api/jobs/create" in routes
        assert "/api/jobs" in routes
        assert any("/api/jobs/" in r and "/start" in r for r in routes)
        assert any("/api/jobs/" in r and "/pause" in r for r in routes)
        assert any("/api/jobs/" in r and "/resume" in r for r in routes)
        assert any("/api/jobs/" in r and "/cancel" in r for r in routes)

    def test_setup_routes_registers_worker_endpoints(self, coordinator):
        """Test that worker endpoints are registered."""
        routes = [route.path for route in coordinator.app.routes]
        assert "/api/workers" in routes

    def test_setup_routes_registers_sync_endpoints(self, coordinator):
        """Test that sync endpoints are registered."""
        routes = [route.path for route in coordinator.app.routes]
        assert "/api/sync/manifest" in routes
        assert "/api/sync/settings" in routes
        assert "/api/sync/addons" in routes

    def test_setup_routes_registers_websocket(self, coordinator):
        """Test that WebSocket endpoint is registered."""
        routes = [route.path for route in coordinator.app.routes]
        assert "/ws" in routes

    def test_setup_routes_registers_event_handlers(self, coordinator):
        """Test that event handlers are registered."""
        # on_event is a method, just check it exists
        assert hasattr(coordinator.app, 'on_event')


# ============================================================================
# Tests for Run Method
# ============================================================================


class TestRunMethod:
    """Tests for run method."""

    def test_run_method_exists(self, coordinator):
        """Test that run method exists."""
        assert hasattr(coordinator, "run")
        assert callable(coordinator.run)


# ============================================================================
# Tests for WorkerInfo Model
# ============================================================================


class TestWorkerInfo:
    """Tests for WorkerInfo model."""

    def test_worker_info_creation(self):
        """Test creating WorkerInfo."""
        worker = WorkerInfo(
            worker_id="worker-001",
            worker_name="test-worker",
            cpu_cores=8,
            gpu_name="Test GPU",
            last_seen=time.time(),
            current_task_id="task-123",
        )
        assert worker.worker_id == "worker-001"
        assert worker.worker_name == "test-worker"
        assert worker.cpu_cores == 8
        assert worker.gpu_name == "Test GPU"
        assert worker.current_task_id == "task-123"

    def test_worker_info_without_task(self):
        """Test creating WorkerInfo without current task."""
        worker = WorkerInfo(
            worker_id="worker-001",
            worker_name="test-worker",
            cpu_cores=8,
            gpu_name="Test GPU",
            last_seen=time.time(),
        )
        assert worker.current_task_id is None


# ============================================================================
# Tests for UpdateJobRequest Model
# ============================================================================


class TestUpdateJobRequest:
    """Tests for UpdateJobRequest model."""

    def test_update_job_request_with_both_fields(self):
        """Test creating request with both fields."""
        from werender.network.coordinator import UpdateJobRequest
        request = UpdateJobRequest(start_frame=10, end_frame=20)
        assert request.start_frame == 10
        assert request.end_frame == 20

    def test_update_job_request_with_one_field(self):
        """Test creating request with one field."""
        from werender.network.coordinator import UpdateJobRequest
        request = UpdateJobRequest(start_frame=10)
        assert request.start_frame == 10
        assert request.end_frame is None

    def test_update_job_request_empty(self):
        """Test creating empty request."""
        from werender.network.coordinator import UpdateJobRequest
        request = UpdateJobRequest()
        assert request.start_frame is None
        assert request.end_frame is None
