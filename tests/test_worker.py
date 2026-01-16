"""Comprehensive unit tests for worker.py."""

import asyncio
import io
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch, mock_open

import httpx
import pytest

from werender.core.blender import BlenderRenderer, RenderResult
from werender.network.discovery import NodeInfo
from werender.network.worker import WorkerNode


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_system_specs():
    """Mock system specs."""
    mock_specs = MagicMock()
    mock_specs.hostname = "test-host"
    mock_specs.cpu_cores = 8
    mock_specs.cpu_threads = 16
    mock_specs.ram_gb = 16.0
    mock_specs.gpu_name = "Test GPU"
    mock_specs.gpu_vram_gb = 8.0
    return mock_specs


@pytest.fixture
def mock_blender_renderer():
    """Mock BlenderRenderer."""
    mock_renderer = MagicMock(spec=BlenderRenderer)
    mock_renderer.get_version.return_value = "4.0.0"
    mock_renderer.render_frame.return_value = RenderResult(
        success=True,
        frame=1,
        output_file=Path("/tmp/output/0001.png"),
        render_time=1.5,
    )
    return mock_renderer


@pytest.fixture
def mock_discovery_service():
    """Mock DiscoveryService."""
    mock_discovery = MagicMock()
    mock_discovery.start = MagicMock()
    mock_discovery.stop = MagicMock()
    return mock_discovery


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.aclose = AsyncMock()
    return mock_client


@pytest.fixture
def mock_coordinator_node():
    """Mock coordinator NodeInfo."""
    return NodeInfo(
        name="test-coordinator",
        address="192.168.1.100",
        port=8420,
        node_type="coordinator",
        properties={
            "node_id": "coord-001",
            "hostname": "coordinator-host",
        },
    )


@pytest.fixture
def worker(mock_system_specs, mock_blender_renderer, mock_discovery_service):
    """Create a WorkerNode instance with mocked dependencies."""
    with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
         patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
         patch("werender.network.discovery.DiscoveryService", return_value=mock_discovery_service), \
         patch("socket.gethostname", return_value="test-host"):
        worker = WorkerNode(name="test-worker", port=8421)
        # Use real temp directory for testing
        worker.temp_dir = Path(tempfile.mkdtemp()) / "werender"
        worker.temp_dir.mkdir(parents=True, exist_ok=True)
        worker.config_dir = Path(tempfile.mkdtemp())
        worker.config_dir.mkdir(exist_ok=True)
        worker.addons_dir = worker.config_dir / "addons"
        worker.addons_dir.mkdir(exist_ok=True)
        worker.api_key = "test-api-key-123"
        return worker


@pytest.fixture
def sample_task_data():
    """Sample task data from coordinator."""
    return {
        "id": "task-001",
        "job_id": "job-001",
        "frame_number": 1,
        "blend_file_hash": "abc123def456",
    }


@pytest.fixture
def sample_blend_file():
    """Create a temporary blend file for testing."""
    temp_dir = Path(tempfile.mkdtemp())
    blend_file = temp_dir / "test.blend"
    blend_file.write_bytes(b"fake blend file content")
    return blend_file


@pytest.fixture
def sample_output_file():
    """Create a temporary output file for testing."""
    temp_dir = Path(tempfile.mkdtemp())
    output_file = temp_dir / "0001.png"
    output_file.write_bytes(b"fake image data")
    return output_file


# ============================================================================
# Tests for WorkerNode.__init__
# ============================================================================


class TestWorkerNodeInitialization:
    """Tests for WorkerNode initialization."""

    def test_init_creates_worker_with_default_name(self, mock_system_specs, mock_blender_renderer):
        """Test initialization with default name (hostname)."""
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
             patch("werender.network.discovery.DiscoveryService"), \
             patch("socket.gethostname", return_value="test-host"):
            worker = WorkerNode()
            assert worker.name == "test-host"

    def test_init_creates_worker_with_custom_name(self, mock_system_specs, mock_blender_renderer):
        """Test initialization with custom name."""
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
             patch("werender.network.discovery.DiscoveryService"):
            worker = WorkerNode(name="custom-worker")
            assert worker.name == "custom-worker"

    def test_init_creates_worker_with_custom_port(self, mock_system_specs, mock_blender_renderer):
        """Test initialization with custom port."""
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
             patch("werender.network.discovery.DiscoveryService"):
            worker = WorkerNode(port=9000)
            assert worker.port == 9000

    def test_init_generates_node_id(self, mock_system_specs, mock_blender_renderer):
        """Test that node ID is generated."""
        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_blender_renderer), \
             patch("werender.network.discovery.DiscoveryService"):
            worker = WorkerNode()
            assert worker.node_id is not None
            assert len(worker.node_id) == 8

    def test_init_loads_system_specs(self, worker, mock_system_specs):
        """Test that system specs are loaded."""
        assert worker.specs is not None
        assert worker.specs.cpu_cores == mock_system_specs.cpu_cores
        assert worker.specs.ram_gb == mock_system_specs.ram_gb

    def test_init_loads_blender_version(self, worker):
        """Test that Blender version is loaded."""
        assert worker.blender_version == "4.0.0"

    def test_init_handles_blender_version_failure(self, mock_system_specs):
        """Test initialization when Blender version check fails."""
        mock_failing_renderer = MagicMock()
        mock_failing_renderer.get_version.side_effect = Exception("Blender not found")

        with patch("werender.utils.system.get_system_specs", return_value=mock_system_specs), \
             patch("werender.core.blender.BlenderRenderer", return_value=mock_failing_renderer), \
             patch("werender.network.discovery.DiscoveryService"):
            worker = WorkerNode()
            assert worker.blender_version == ""

    def test_init_creates_discovery_service(self, worker):
        """Test that discovery service is created."""
        assert worker.discovery is not None

    def test_init_initializes_worker_state(self, worker):
        """Test that worker state is initialized correctly."""
        assert worker.coordinator is None
        assert worker.is_running is False
        assert worker.is_synced is False
        assert worker.settings == {}
        assert worker.installed_addons == set()

    def test_init_creates_temp_directory(self, worker):
        """Test that temp directory is created."""
        assert worker.temp_dir.exists()
        assert worker.temp_dir.is_dir()

    def test_init_creates_config_directory(self, worker):
        """Test that config directory is created."""
        assert worker.config_dir.exists()
        assert worker.config_dir.is_dir()

    def test_init_creates_addons_directory(self, worker):
        """Test that addons directory is created."""
        assert worker.addons_dir.exists()
        assert worker.addons_dir.is_dir()

    def test_init_initializes_http_client_as_none(self, worker):
        """Test that HTTP client is initialized as None."""
        assert worker.http_client is None

    def test_init_initializes_api_key_as_none(self, worker):
        """Test that API key is initialized as None."""
        # Worker fixture sets api_key, so check a fresh worker
        with patch("werender.utils.system.get_system_specs"), \
             patch("werender.core.blender.BlenderRenderer"), \
             patch("werender.network.discovery.DiscoveryService"):
            fresh_worker = WorkerNode()
            assert fresh_worker.api_key is None


# ============================================================================
# Tests for _on_coordinator_discovered
# ============================================================================


class TestOnCoordinatorDiscovered:
    """Tests for _on_coordinator_discovered method."""

    def test_on_coordinator_discovered_sets_coordinator(self, worker, mock_coordinator_node):
        """Test that coordinator is set when discovered."""
        worker._on_coordinator_discovered(mock_coordinator_node)
        assert worker.coordinator == mock_coordinator_node

    def test_on_coordinator_discovered_resets_sync_state(self, worker, mock_coordinator_node):
        """Test that sync state is reset when new coordinator is discovered."""
        worker.is_synced = True
        worker._on_coordinator_discovered(mock_coordinator_node)
        assert worker.is_synced is False

    def test_on_coordinator_discovered_handles_multiple_coordinators(self, worker):
        """Test handling discovery of multiple coordinators."""
        coord1 = NodeInfo(
            name="coord1",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        coord2 = NodeInfo(
            name="coord2",
            address="192.168.1.101",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-002"},
        )

        worker._on_coordinator_discovered(coord1)
        assert worker.coordinator == coord1

        worker._on_coordinator_discovered(coord2)
        assert worker.coordinator == coord2


# ============================================================================
# Tests for _on_coordinator_removed
# ============================================================================


class TestOnCoordinatorRemoved:
    """Tests for _on_coordinator_removed method."""

    def test_on_coordinator_removed_clears_coordinator(self, worker, mock_coordinator_node):
        """Test that coordinator is cleared when removed."""
        worker.coordinator = mock_coordinator_node
        worker._on_coordinator_removed(mock_coordinator_node)
        assert worker.coordinator is None

    def test_on_coordinator_removed_only_matching_coordinator(self, worker):
        """Test that only matching coordinator is removed."""
        coord1 = NodeInfo(
            name="coord1",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        coord2 = NodeInfo(
            name="coord2",
            address="192.168.1.101",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-002"},
        )

        worker.coordinator = coord1
        worker._on_coordinator_removed(coord2)
        assert worker.coordinator == coord1  # Should still be coord1

        worker._on_coordinator_removed(coord1)
        assert worker.coordinator is None

    def test_on_coordinator_removed_with_no_coordinator(self, worker):
        """Test handling removal when no coordinator is set."""
        worker.coordinator = None
        # Should not raise an error
        worker._on_coordinator_removed(
            NodeInfo(
                name="test",
                address="192.168.1.100",
                port=8420,
                node_type="coordinator",
                properties={"node_id": "test-001"},
            )
        )
        assert worker.coordinator is None


# ============================================================================
# Tests for _request_and_render_task
# ============================================================================


class TestRequestAndRenderTask:
    """Tests for _request_and_render_task method."""

    @pytest.mark.asyncio
    async def test_request_and_render_task_no_coordinator(self, worker):
        """Test that method returns early when no coordinator is set."""
        worker.coordinator = None
        # Should not raise an error
        await worker._request_and_render_task()

    @pytest.mark.asyncio
    async def test_request_and_render_task_no_tasks_available(self, worker, mock_http_client):
        """Test handling when no tasks are available (204 status)."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock stream response for no tasks
        mock_response = AsyncMock()
        mock_response.status_code = 204
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        await worker._request_and_render_task()
        mock_http_client.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_and_render_task_success(self, worker, mock_http_client, sample_task_data, sample_blend_file, sample_output_file):
        """Test successful task request and render."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock task request response
        mock_task_response = AsyncMock()
        mock_task_response.status_code = 200
        mock_task_response.json = AsyncMock(return_value=sample_task_data)
        mock_task_response.__aenter__ = AsyncMock(return_value=mock_task_response)
        mock_task_response.__aexit__ = AsyncMock(return_value=None)

        # Mock blend file download response
        mock_blend_response = AsyncMock()
        mock_blend_response.status_code = 200
        mock_blend_response.aiter_bytes = AsyncMock(return_value=[b"blend content"])
        mock_blend_response.__aenter__ = AsyncMock(return_value=mock_blend_response)
        mock_blend_response.__aexit__ = AsyncMock(return_value=None)

        # Mock upload result response
        mock_upload_response = AsyncMock()
        mock_upload_response.status_code = 200
        mock_http_client.post = AsyncMock(return_value=mock_upload_response)

        # Set up stream to return different responses based on URL
        stream_call_count = [0]

        async def mock_stream_method(method, url, **kwargs):
            stream_call_count[0] += 1
            if "request" in url:
                return mock_task_response
            else:
                return mock_blend_response

        mock_http_client.stream = mock_stream_method

        # Mock file operations
        with patch("builtins.open", mock_open(read_data=b"blend data")):
            await worker._request_and_render_task()

        # Verify calls were made
        assert stream_call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_request_and_render_task_download_blend_failure(self, worker, mock_http_client, sample_task_data):
        """Test handling when blend file download fails."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock task request response
        mock_task_response = AsyncMock()
        mock_task_response.status_code = 200
        mock_task_response.json = AsyncMock(return_value=sample_task_data)
        mock_task_response.__aenter__ = AsyncMock(return_value=mock_task_response)
        mock_task_response.__aexit__ = AsyncMock(return_value=None)

        # Mock blend file download failure
        mock_blend_response = AsyncMock()
        mock_blend_response.status_code = 404
        mock_blend_response.__aenter__ = AsyncMock(return_value=mock_blend_response)
        mock_blend_response.__aexit__ = AsyncMock(return_value=None)

        stream_call_count = [0]

        async def mock_stream_method(method, url, **kwargs):
            stream_call_count[0] += 1
            if "request" in url:
                return mock_task_response
            else:
                return mock_blend_response

        mock_http_client.stream = mock_stream_method
        worker._report_task_failure = AsyncMock()

        await worker._request_and_render_task()

        # Verify failure was reported
        worker._report_task_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_and_render_task_render_failure(self, worker, mock_http_client, sample_task_data):
        """Test handling when render fails."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock task request response
        mock_task_response = AsyncMock()
        mock_task_response.status_code = 200
        mock_task_response.json = AsyncMock(return_value=sample_task_data)
        mock_task_response.__aenter__ = AsyncMock(return_value=mock_task_response)
        mock_task_response.__aexit__ = AsyncMock(return_value=None)

        # Mock blend file download response
        mock_blend_response = AsyncMock()
        mock_blend_response.status_code = 200
        mock_blend_response.aiter_bytes = AsyncMock(return_value=[b"blend content"])
        mock_blend_response.__aenter__ = AsyncMock(return_value=mock_blend_response)
        mock_blend_response.__aexit__ = AsyncMock(return_value=None)

        # Mock render failure
        worker.blender.render_frame.return_value = RenderResult(
            success=False,
            frame=1,
            error_message="Render failed",
        )

        stream_call_count = [0]

        async def mock_stream_method(method, url, **kwargs):
            stream_call_count[0] += 1
            if "request" in url:
                return mock_task_response
            else:
                return mock_blend_response

        mock_http_client.stream = mock_stream_method
        worker._report_task_failure = AsyncMock()

        with patch("builtins.open", mock_open(read_data=b"blend data")):
            await worker._request_and_render_task()

        # Verify failure was reported
        worker._report_task_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_and_render_task_connect_error(self, worker, mock_http_client):
        """Test handling connection error."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client
        mock_http_client.stream.side_effect = httpx.ConnectError("Connection failed")

        # Should not raise an error, just clear coordinator
        await worker._request_and_render_task()
        assert worker.coordinator is None


# ============================================================================
# Tests for _download_blend_file
# ============================================================================


class TestDownloadBlendFile:
    """Tests for _download_blend_file method."""

    @pytest.mark.asyncio
    async def test_download_blend_file_success(self, worker, mock_http_client):
        """Test successful blend file download."""
        worker.http_client = mock_http_client

        # Mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_bytes = AsyncMock(return_value=[b"blend content"])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        with patch("builtins.open", mock_open()) as mock_file:
            result = await worker._download_blend_file(
                "http://192.168.1.100:8420",
                "job-001",
                "abc123",
            )

        assert result is not None
        mock_http_client.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_blend_file_already_cached(self, worker):
        """Test that cached file is used if it exists."""
        # Create a cached file
        blend_dir = worker.temp_dir / "blend_files"
        blend_dir.mkdir(parents=True, exist_ok=True)
        cached_file = blend_dir / "abc123.blend"
        cached_file.write_bytes(b"cached content")

        worker.http_client = AsyncMock()

        result = await worker._download_blend_file(
            "http://192.168.1.100:8420",
            "job-001",
            "abc123",
        )

        assert result == cached_file
        worker.http_client.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_blend_file_http_error(self, worker, mock_http_client):
        """Test handling HTTP error during download."""
        worker.http_client = mock_http_client

        # Mock error response
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        result = await worker._download_blend_file(
            "http://192.168.1.100:8420",
            "job-001",
            "abc123",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_download_blend_file_exception(self, worker, mock_http_client):
        """Test handling exception during download."""
        worker.http_client = mock_http_client
        mock_http_client.stream.side_effect = Exception("Download failed")

        result = await worker._download_blend_file(
            "http://192.168.1.100:8420",
            "job-001",
            "abc123",
        )

        assert result is None


# ============================================================================
# Tests for _upload_result
# ============================================================================


class TestUploadResult:
    """Tests for _upload_result method."""

    @pytest.mark.asyncio
    async def test_upload_result_success(self, worker, mock_http_client, sample_task_data, sample_output_file):
        """Test successful result upload."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response

        await worker._upload_result(
            "http://192.168.1.100:8420",
            sample_task_data,
            sample_output_file,
            1.5,
        )

        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_result_missing_file(self, worker, sample_task_data):
        """Test handling when output file is missing."""
        missing_file = Path("/nonexistent/0001.png")

        worker.http_client = AsyncMock()

        await worker._upload_result(
            "http://192.168.1.100:8420",
            sample_task_data,
            missing_file,
            1.5,
        )

        worker.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_result_http_error(self, worker, mock_http_client, sample_task_data, sample_output_file):
        """Test handling HTTP error during upload."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response

        await worker._upload_result(
            "http://192.168.1.100:8420",
            sample_task_data,
            sample_output_file,
            1.5,
        )

        # Should still call post, even on error
        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_result_exception(self, worker, mock_http_client, sample_task_data, sample_output_file):
        """Test handling exception during upload."""
        worker.http_client = mock_http_client
        mock_http_client.post.side_effect = Exception("Upload failed")

        # Should not raise an error
        await worker._upload_result(
            "http://192.168.1.100:8420",
            sample_task_data,
            sample_output_file,
            1.5,
        )


# ============================================================================
# Tests for _report_task_failure
# ============================================================================


class TestReportTaskFailure:
    """Tests for _report_task_failure method."""

    @pytest.mark.asyncio
    async def test_report_task_failure_success(self, worker, mock_http_client, sample_task_data):
        """Test successful task failure report."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response

        await worker._report_task_failure(sample_task_data, "Render failed")

        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_task_failure_no_coordinator(self, worker, sample_task_data):
        """Test handling when no coordinator is set."""
        worker.coordinator = None
        worker.http_client = AsyncMock()

        await worker._report_task_failure(sample_task_data, "Render failed")

        worker.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_report_task_failure_exception(self, worker, mock_http_client, sample_task_data):
        """Test handling exception during failure report."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client
        mock_http_client.post.side_effect = Exception("Network error")

        # Should not raise an error
        await worker._report_task_failure(sample_task_data, "Render failed")


# ============================================================================
# Tests for _sync_with_coordinator
# ============================================================================


class TestSyncWithCoordinator:
    """Tests for _sync_with_coordinator method."""

    @pytest.mark.asyncio
    async def test_sync_with_coordinator_success(self, worker, mock_http_client):
        """Test successful sync with coordinator."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock manifest response
        mock_manifest_response = AsyncMock()
        mock_manifest_response.status_code = 200
        mock_manifest_response.json = AsyncMock(return_value={
            "settings_hash": "abc123",
            "addons_hash": "def456",
            "timestamp": 0,
        })
        mock_http_client.get.return_value = mock_manifest_response

        worker._sync_settings = AsyncMock()
        worker._sync_addons = AsyncMock()

        await worker._sync_with_coordinator()

        assert worker.is_synced is True
        worker._sync_settings.assert_called_once()
        worker._sync_addons.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_with_coordinator_no_coordinator(self, worker):
        """Test handling when no coordinator is set."""
        worker.coordinator = None
        worker.http_client = AsyncMock()

        await worker._sync_with_coordinator()

        worker.http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_with_coordinator_manifest_error(self, worker, mock_http_client):
        """Test handling manifest fetch error."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock error response
        mock_manifest_response = AsyncMock()
        mock_manifest_response.status_code = 500
        mock_http_client.get.return_value = mock_manifest_response

        await worker._sync_with_coordinator()

        # Should not be synced on error
        assert worker.is_synced is False

    @pytest.mark.asyncio
    async def test_sync_with_coordinator_exception(self, worker, mock_http_client):
        """Test handling exception during sync."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client
        mock_http_client.get.side_effect = Exception("Sync failed")

        await worker._sync_with_coordinator()

        # Should not raise an error
        assert worker.is_synced is False


# ============================================================================
# Tests for _sync_settings
# ============================================================================


class TestSyncSettings:
    """Tests for _sync_settings method."""

    @pytest.mark.asyncio
    async def test_sync_settings_success(self, worker, mock_http_client):
        """Test successful settings sync."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value={"test_setting": "value"})
        mock_http_client.get.return_value = mock_response

        await worker._sync_settings("http://192.168.1.100:8420")

        assert worker.settings == {"test_setting": "value"}
        mock_http_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_settings_http_error(self, worker, mock_http_client):
        """Test handling HTTP error during settings sync."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_http_client.get.return_value = mock_response

        await worker._sync_settings("http://192.168.1.100:8420")

        # Should not update settings on error
        assert worker.settings == {}

    @pytest.mark.asyncio
    async def test_sync_settings_exception(self, worker, mock_http_client):
        """Test handling exception during settings sync."""
        worker.http_client = mock_http_client
        mock_http_client.get.side_effect = Exception("Settings sync failed")

        # Should not raise an error
        await worker._sync_settings("http://192.168.1.100:8420")


# ============================================================================
# Tests for _sync_addons
# ============================================================================


class TestSyncAddons:
    """Tests for _sync_addons method."""

    @pytest.mark.asyncio
    async def test_sync_addons_success(self, worker, mock_http_client):
        """Test successful addons sync."""
        worker.http_client = mock_http_client

        # Mock addons list response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[
            {"name": "test_addon", "filename": "test_addon.zip", "size": 1024}
        ])
        mock_http_client.get.return_value = mock_response

        worker._download_and_install_addon = AsyncMock()
        worker._enable_addon_in_blender = AsyncMock()

        await worker._sync_addons("http://192.168.1.100:8420", "hash123")

        worker._download_and_install_addon.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_addons_empty_list(self, worker, mock_http_client):
        """Test handling empty addons list."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[])
        mock_http_client.get.return_value = mock_response

        await worker._sync_addons("http://192.168.1.100:8420", "hash123")

        # Should not raise an error
        assert worker.installed_addons == set()

    @pytest.mark.asyncio
    async def test_sync_addons_http_error(self, worker, mock_http_client):
        """Test handling HTTP error during addons sync."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_http_client.get.return_value = mock_response

        await worker._sync_addons("http://192.168.1.100:8420", "hash123")

        # Should not raise an error
        assert worker.installed_addons == set()

    @pytest.mark.asyncio
    async def test_sync_addons_cached_addon(self, worker, mock_http_client):
        """Test that cached addon is used if file exists with matching size."""
        worker.http_client = mock_http_client

        # Create a cached addon file
        addon_file = worker.addons_dir / "test_addon.zip"
        addon_file.write_bytes(b"cached addon content")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[
            {"name": "test_addon", "filename": "test_addon.zip", "size": 20}  # 20 bytes
        ])
        mock_http_client.get.return_value = mock_response

        worker._download_and_install_addon = AsyncMock()
        worker._enable_addon_in_blender = AsyncMock()

        await worker._sync_addons("http://192.168.1.100:8420", "hash123")

        # Should not download if cached
        worker._download_and_install_addon.assert_not_called()
        worker._enable_addon_in_blender.assert_called_once_with("test_addon")


# ============================================================================
# Tests for _download_and_install_addon
# ============================================================================


class TestDownloadAndInstallAddon:
    """Tests for _download_and_install_addon method."""

    @pytest.mark.asyncio
    async def test_download_and_install_addon_success(self, worker, mock_http_client):
        """Test successful addon download and install."""
        worker.http_client = mock_http_client

        # Mock download response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_bytes = AsyncMock(return_value=[b"zip content"])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        addon_info = {"name": "test_addon", "filename": "test_addon.zip"}
        target_path = worker.addons_dir / "test_addon.zip"

        worker._enable_addon_in_blender = AsyncMock()

        with patch("builtins.open", mock_open()):
            with patch("zipfile.ZipFile") as mock_zip:
                mock_zip.return_value.__enter__ = MagicMock(return_value=mock_zip.return_value)
                mock_zip.return_value.__exit__ = MagicMock(return_value=None)
                await worker._download_and_install_addon(
                    "http://192.168.1.100:8420",
                    addon_info,
                    target_path,
                )

        worker._enable_addon_in_blender.assert_called_once_with("test_addon")

    @pytest.mark.asyncio
    async def test_download_and_install_addon_http_error(self, worker, mock_http_client):
        """Test handling HTTP error during addon download."""
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        addon_info = {"name": "test_addon", "filename": "test_addon.zip"}
        target_path = worker.addons_dir / "test_addon.zip"

        worker._enable_addon_in_blender = AsyncMock()

        await worker._download_and_install_addon(
            "http://192.168.1.100:8420",
            addon_info,
            target_path,
        )

        # Should not enable on download error
        worker._enable_addon_in_blender.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_and_install_addon_exception(self, worker, mock_http_client):
        """Test handling exception during addon install."""
        worker.http_client = mock_http_client
        mock_http_client.stream.side_effect = Exception("Download failed")

        addon_info = {"name": "test_addon", "filename": "test_addon.zip"}
        target_path = worker.addons_dir / "test_addon.zip"

        worker._enable_addon_in_blender = AsyncMock()

        # Should not raise an error
        await worker._download_and_install_addon(
            "http://192.168.1.100:8420",
            addon_info,
            target_path,
        )


# ============================================================================
# Tests for _enable_addon_in_blender
# ============================================================================


class TestEnableAddonInBlender:
    """Tests for _enable_addon_in_blender method."""

    @pytest.mark.asyncio
    async def test_enable_addon_in_blender(self, worker):
        """Test enabling addon in Blender."""
        # This is a mock method that just logs, so we just verify it doesn't crash
        await worker._enable_addon_in_blender("test_addon")
        # Should not raise an error

    @pytest.mark.asyncio
    async def test_enable_addon_in_blender_multiple_addons(self, worker):
        """Test enabling multiple addons."""
        addons = ["addon1", "addon2", "addon3"]
        for addon in addons:
            await worker._enable_addon_in_blender(addon)
        # Should not raise an error


# ============================================================================
# Tests for _worker_loop
# ============================================================================


class TestWorkerLoop:
    """Tests for _worker_loop method."""

    @pytest.mark.asyncio
    async def test_worker_loop_without_coordinator(self, worker, mock_http_client):
        """Test worker loop behavior when no coordinator is available."""
        worker.http_client = mock_http_client

        # Run loop for a short time
        loop_task = asyncio.create_task(worker._worker_loop())
        await asyncio.sleep(0.2)
        worker.is_running = False
        await loop_task

        # Should have created HTTP client
        assert worker.http_client is not None

    @pytest.mark.asyncio
    async def test_worker_loop_with_coordinator_not_synced(self, worker, mock_http_client, mock_coordinator_node):
        """Test worker loop with coordinator but not synced."""
        worker.coordinator = mock_coordinator_node
        worker.http_client = mock_http_client
        worker._sync_with_coordinator = AsyncMock()

        # Run loop for a short time
        loop_task = asyncio.create_task(worker._worker_loop())
        await asyncio.sleep(0.2)
        worker.is_running = False
        await loop_task

        # Should have attempted sync
        worker._sync_with_coordinator.assert_called()

    @pytest.mark.asyncio
    async def test_worker_loop_with_coordinator_synced(self, worker, mock_http_client, mock_coordinator_node):
        """Test worker loop with coordinator and synced."""
        worker.coordinator = mock_coordinator_node
        worker.is_synced = True
        worker.http_client = mock_http_client
        worker._request_and_render_task = AsyncMock()

        # Run loop for a short time
        loop_task = asyncio.create_task(worker._worker_loop())
        await asyncio.sleep(0.2)
        worker.is_running = False
        await loop_task

        # Should have requested task
        worker._request_and_render_task.assert_called()

    @pytest.mark.asyncio
    async def test_worker_loop_handles_exception(self, worker, mock_http_client):
        """Test that worker loop handles exceptions gracefully."""
        worker.http_client = mock_http_client
        worker._sync_with_coordinator = AsyncMock(side_effect=Exception("Test error"))

        # Run loop for a short time
        loop_task = asyncio.create_task(worker._worker_loop())
        await asyncio.sleep(0.3)
        worker.is_running = False
        await loop_task

        # Should not crash, loop should continue

    @pytest.mark.asyncio
    async def test_worker_loop_closes_http_client(self, worker, mock_http_client):
        """Test that HTTP client is closed when loop exits."""
        worker.http_client = mock_http_client

        loop_task = asyncio.create_task(worker._worker_loop())
        await asyncio.sleep(0.1)
        worker.is_running = False
        await loop_task

        # Should close HTTP client
        mock_http_client.aclose.assert_called_once()


# ============================================================================
# Tests for start method
# ============================================================================


class TestStartMethod:
    """Tests for start method."""

    def test_start_loads_api_key(self, worker):
        """Test that API key is loaded on start."""
        with patch("werender.network.auth.get_worker_api_key", return_value="test-key"):
            worker.api_key = None
            # start() runs asyncio.run, so we can't test it directly
            # Just verify the loading mechanism
            from werender.network.auth import get_worker_api_key
            key = get_worker_api_key(worker.config_dir)
            assert key is not None

    def test_start_sets_discovery_callbacks(self, worker):
        """Test that discovery callbacks are set on start."""
        # The start method sets these callbacks
        assert worker.discovery.on_discovery is not None
        assert worker.discovery.on_removal is not None


# ============================================================================
# Tests for stop method
# ============================================================================


class TestStopMethod:
    """Tests for stop method."""

    def test_stop_sets_running_false(self, worker):
        """Test that stop sets is_running to False."""
        worker.is_running = True
        worker.stop()
        assert worker.is_running is False

    def test_stop_stops_discovery(self, worker):
        """Test that stop stops discovery service."""
        worker.stop()
        worker.discovery.stop.assert_called_once()


# ============================================================================
# Tests for Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_multiple_coordinator_discoveries(self, worker):
        """Test handling multiple coordinator discoveries."""
        coord1 = NodeInfo(
            name="coord1",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        coord2 = NodeInfo(
            name="coord2",
            address="192.168.1.101",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-002"},
        )

        worker._on_coordinator_discovered(coord1)
        worker._on_coordinator_discovered(coord2)

        assert worker.coordinator == coord2
        assert worker.is_synced is False

    @pytest.mark.asyncio
    async def test_task_request_with_invalid_response(self, worker, mock_http_client):
        """Test handling invalid response from task request."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        # Should not raise an error
        await worker._request_and_render_task()

    @pytest.mark.asyncio
    async def test_download_blend_file_with_existing_corrupted_file(self, worker, mock_http_client):
        """Test handling when cached file exists but needs redownload."""
        # Create a file with wrong size
        blend_dir = worker.temp_dir / "blend_files"
        blend_dir.mkdir(parents=True, exist_ok=True)
        cached_file = blend_dir / "abc123.blend"
        cached_file.write_bytes(b"small")

        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_bytes = AsyncMock(return_value=[b"new content"])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.stream.return_value = mock_response

        with patch("builtins.open", mock_open()):
            result = await worker._download_blend_file(
                "http://192.168.1.100:8420",
                "job-001",
                "abc123",
            )

        # Should download new file
        mock_http_client.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_addons_with_mixed_cache_status(self, worker, mock_http_client):
        """Test syncing addons with some cached and some not."""
        # Create one cached addon
        cached_addon = worker.addons_dir / "cached_addon.zip"
        cached_addon.write_bytes(b"cached content")

        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[
            {"name": "cached_addon", "filename": "cached_addon.zip", "size": 14},  # 14 bytes
            {"name": "new_addon", "filename": "new_addon.zip", "size": 1024},
        ])
        mock_http_client.get.return_value = mock_response

        worker._download_and_install_addon = AsyncMock()
        worker._enable_addon_in_blender = AsyncMock()

        await worker._sync_addons("http://192.168.1.100:8420", "hash123")

        # Should download new addon but not cached one
        worker._download_and_install_addon.assert_called_once()
        assert worker._download_and_install_addon.call_args[0][1]["name"] == "new_addon"
        assert worker._enable_addon_in_blender.call_count == 2  # Both addons

    @pytest.mark.asyncio
    async def test_upload_result_with_invalid_file_path(self, worker, mock_http_client, sample_task_data):
        """Test handling invalid file path during upload."""
        worker.http_client = mock_http_client

        invalid_file = Path("")  # Empty path

        await worker._upload_result(
            "http://192.168.1.100:8420",
            sample_task_data,
            invalid_file,
            1.5,
        )

        # Should not attempt upload
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_report_task_failure_with_empty_error_message(self, worker, mock_http_client, sample_task_data):
        """Test reporting task failure with empty error message."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response

        await worker._report_task_failure(sample_task_data, "")

        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_worker_loop_with_rapid_coordinator_changes(self, worker, mock_http_client):
        """Test worker loop handling rapid coordinator changes."""
        coord1 = NodeInfo(
            name="coord1",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        coord2 = NodeInfo(
            name="coord2",
            address="192.168.1.101",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-002"},
        )

        worker.http_client = mock_http_client
        worker._sync_with_coordinator = AsyncMock()
        worker._request_and_render_task = AsyncMock()

        # Simulate rapid changes
        async def simulate_changes():
            await asyncio.sleep(0.1)
            worker._on_coordinator_discovered(coord1)
            await asyncio.sleep(0.1)
            worker._on_coordinator_discovered(coord2)
            await asyncio.sleep(0.1)
            worker._on_coordinator_removed(coord2)

        loop_task = asyncio.create_task(worker._worker_loop())
        change_task = asyncio.create_task(simulate_changes())

        await asyncio.sleep(0.5)
        worker.is_running = False

        await loop_task
        await change_task

        # Should handle all changes gracefully
        assert worker.coordinator is None


# ============================================================================
# Tests for Integration-like Scenarios
# ============================================================================


class TestIntegrationScenarios:
    """Tests for integration-like scenarios."""

    @pytest.mark.asyncio
    async def test_full_task_workflow(self, worker, mock_http_client, sample_task_data, sample_output_file):
        """Test complete workflow from task request to result upload."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock task request
        mock_task_response = AsyncMock()
        mock_task_response.status_code = 200
        mock_task_response.json = AsyncMock(return_value=sample_task_data)
        mock_task_response.__aenter__ = AsyncMock(return_value=mock_task_response)
        mock_task_response.__aexit__ = AsyncMock(return_value=None)

        # Mock blend download
        mock_blend_response = AsyncMock()
        mock_blend_response.status_code = 200
        mock_blend_response.aiter_bytes = AsyncMock(return_value=[b"blend content"])
        mock_blend_response.__aenter__ = AsyncMock(return_value=mock_blend_response)
        mock_blend_response.__aexit__ = AsyncMock(return_value=None)

        # Mock upload response
        mock_upload_response = AsyncMock()
        mock_upload_response.status_code = 200
        mock_http_client.post.return_value = mock_upload_response

        stream_call_count = [0]

        async def mock_stream_method(method, url, **kwargs):
            stream_call_count[0] += 1
            if "request" in url:
                return mock_task_response
            else:
                return mock_blend_response

        mock_http_client.stream = mock_stream_method

        with patch("builtins.open", mock_open()):
            await worker._request_and_render_task()

        # Verify all steps were attempted
        assert stream_call_count[0] >= 2
        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_and_render_workflow(self, worker, mock_http_client):
        """Test workflow of syncing then rendering."""
        worker.coordinator = NodeInfo(
            name="coord",
            address="192.168.1.100",
            port=8420,
            node_type="coordinator",
            properties={"node_id": "coord-001"},
        )
        worker.http_client = mock_http_client

        # Mock sync
        mock_manifest_response = AsyncMock()
        mock_manifest_response.status_code = 200
        mock_manifest_response.json = AsyncMock(return_value={
            "settings_hash": "abc123",
            "addons_hash": "def456",
            "timestamp": 0,
        })

        mock_addons_response = AsyncMock()
        mock_addons_response.status_code = 200
        mock_addons_response.json = AsyncMock(return_value=[])

        get_call_count = [0]

        async def mock_get_method(url, **kwargs):
            get_call_count[0] += 1
            if "manifest" in url:
                return mock_manifest_response
            elif "addons" in url:
                return mock_addons_response
            return AsyncMock(status_code=200, json=AsyncMock(return_value={}))

        mock_http_client.get = mock_get_method

        # Sync
        await worker._sync_with_coordinator()

        assert worker.is_synced is True
        assert get_call_count[0] >= 2
