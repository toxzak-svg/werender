"""Comprehensive tests for discovery service."""

import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from werender.network.discovery import DiscoveryService, NodeInfo


class TestNodeInfo:
    """Tests for NodeInfo class."""

    def test_node_info_basic(self):
        """Test basic NodeInfo creation."""
        properties = {
            "node_id": "test-node",
            "hostname": "test-host",
            "blender_version": "3.6.0",
            "cpu_cores": "8",
            "gpu_name": "RTX 3080",
        }

        info = NodeInfo(
            name="Test Node",
            address="192.168.1.100",
            port=8080,
            node_type="worker",
            properties=properties,
        )

        assert info.name == "Test Node"
        assert info.address == "192.168.1.100"
        assert info.port == 8080
        assert info.node_type == "worker"

    def test_node_info_properties(self):
        """Test NodeInfo property accessors."""
        properties = {
            "node_id": "test-id",
            "hostname": "my-host",
            "blender_version": "4.0.0",
            "cpu_cores": "16",
            "gpu_name": "RTX 4090",
        }

        info = NodeInfo(
            name="Node", address="10.0.0.1", port=9000, node_type="coordinator", properties=properties
        )

        assert info.node_id == "test-id"
        assert info.hostname == "my-host"
        assert info.blender_version == "4.0.0"
        assert info.cpu_cores == 16
        assert info.gpu_name == "RTX 4090"

    def test_node_info_default_properties(self):
        """Test NodeInfo with missing properties."""
        info = NodeInfo(
            name="Node", address="127.0.0.1", port=8080, node_type="worker", properties={}
        )

        assert info.node_id == "Node"  # Falls back to name
        assert info.hostname == ""
        assert info.blender_version == ""
        assert info.cpu_cores == 0
        assert info.gpu_name == ""

    def test_node_info_repr(self):
        """Test NodeInfo string representation."""
        info = NodeInfo(
            name="Test", address="192.168.1.1", port=8080, node_type="worker", properties={}
        )

        repr_str = repr(info)
        assert "Test" in repr_str
        assert "worker" in repr_str
        assert "192.168.1.1:8080" in repr_str

    def test_node_info_last_seen(self):
        """Test NodeInfo last_seen timestamp."""
        before = time.time()
        info = NodeInfo(
            name="Node", address="127.0.0.1", port=8080, node_type="worker", properties={}
        )
        after = time.time()

        assert before <= info.last_seen <= after


class TestDiscoveryServiceInit:
    """Tests for DiscoveryService initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test-worker", properties={}
        )

        assert service.node_type == "worker"
        assert service.port == 8080
        assert service.node_id == "test-worker"
        assert service.properties == {}
        assert service.zeroconf is None
        assert service.service_info is None
        assert service.browser is None
        assert service.discovered_nodes == {}
        assert service.on_discovery is None
        assert service.on_removal is None

    def test_init_with_properties(self):
        """Test initialization with properties."""
        props = {"cpu_cores": 8, "gpu_name": "RTX 3080"}

        service = DiscoveryService(
            node_type="coordinator", port=8420, node_id="coord-1", properties=props
        )

        assert service.properties == props

    def test_init_with_callbacks(self):
        """Test initialization with discovery/removal callbacks."""
        on_disc = Mock()
        on_rem = Mock()

        service = DiscoveryService(
            node_type="worker",
            port=8080,
            node_id="test",
            properties={},
        )
        service.on_discovery = on_disc
        service.on_removal = on_rem

        assert service.on_discovery == on_disc
        assert service.on_removal == on_rem


class TestDiscoveryServiceGetLocalIP:
    """Tests for _get_local_ip method."""

    @patch("werender.network.discovery.socket")
    def test_get_local_ip_success(self, mock_socket):
        """Test successful local IP retrieval."""
        mock_sock = MagicMock()
        mock_socket.socket.return_value = mock_sock
        mock_sock.getsockname.return_value = ("192.168.1.100", 12345)

        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        ip = service._get_local_ip()

        assert ip == "192.168.1.100"
        mock_sock.connect.assert_called_once_with(("8.8.8.8", 80))
        mock_sock.close.assert_called_once()

    @patch("werender.network.discovery.socket")
    def test_get_local_ip_fallback(self, mock_socket):
        """Test local IP retrieval fallback on error."""
        mock_socket.socket.side_effect = Exception("Network error")

        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        ip = service._get_local_ip()

        assert ip == "127.0.0.1"


class TestDiscoveryServiceGetNodes:
    """Tests for get_nodes method."""

    def test_get_nodes_empty(self):
        """Test getting nodes when none discovered."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        nodes = service.get_nodes()

        assert nodes == []

    def test_get_nodes_all(self):
        """Test getting all discovered nodes."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        node1 = NodeInfo(
            name="Node1",
            address="192.168.1.1",
            port=8080,
            node_type="coordinator",
            properties={"node_id": "coord-1"},
        )
        node2 = NodeInfo(
            name="Node2",
            address="192.168.1.2",
            port=8081,
            node_type="worker",
            properties={"node_id": "worker-1"},
        )

        service.discovered_nodes["coord-1"] = node1
        service.discovered_nodes["worker-1"] = node2

        nodes = service.get_nodes()

        assert len(nodes) == 2
        assert node1 in nodes
        assert node2 in nodes

    def test_get_nodes_filtered(self):
        """Test getting nodes filtered by type."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        coord = NodeInfo(
            name="Coord",
            address="192.168.1.1",
            port=8080,
            node_type="coordinator",
            properties={"node_id": "coord-1"},
        )
        worker1 = NodeInfo(
            name="Worker1",
            address="192.168.1.2",
            port=8081,
            node_type="worker",
            properties={"node_id": "worker-1"},
        )
        worker2 = NodeInfo(
            name="Worker2",
            address="192.168.1.3",
            port=8082,
            node_type="worker",
            properties={"node_id": "worker-2"},
        )

        service.discovered_nodes["coord-1"] = coord
        service.discovered_nodes["worker-1"] = worker1
        service.discovered_nodes["worker-2"] = worker2

        workers = service.get_nodes(node_type="worker")

        assert len(workers) == 2
        assert worker1 in workers
        assert worker2 in workers
        assert coord not in workers


class TestDiscoveryServiceStop:
    """Tests for stop method."""

    @patch("werender.network.discovery.Zeroconf")
    def test_stop_with_browser(self, mock_zeroconf):
        """Test stopping service with active browser."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.browser = Mock()
        service.service_info = Mock()
        service.zeroconf = Mock()
        service.discovered_nodes = {"test": Mock()}

        service.stop()

        service.browser.cancel.assert_called_once()
        service.zeroconf.unregister_service.assert_called_once()
        service.zeroconf.close.assert_called_once()
        assert service.discovered_nodes == {}

    @patch("werender.network.discovery.Zeroconf")
    def test_stop_no_browser(self, mock_zeroconf):
        """Test stopping service without browser."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = None
        service.zeroconf = None

        service.stop()

        # Should not raise any errors
        assert service.browser is None


class TestDiscoveryServiceHandleServiceRemoved:
    """Tests for _handle_service_removed method."""

    def test_handle_service_removed_existing(self):
        """Test removing an existing service."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        node = NodeInfo(
            name="Node1",
            address="192.168.1.1",
            port=8080,
            node_type="coordinator",
            properties={"node_id": "node-1"},
        )
        service.discovered_nodes["node-1"] = node

        callback = Mock()
        service.on_removal = callback

        service._handle_service_removed("Node1")

        assert "node-1" not in service.discovered_nodes
        callback.assert_called_once_with(node)

    def test_handle_service_removed_nonexistent(self):
        """Test removing a non-existent service."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        callback = Mock()
        service.on_removal = callback

        service._handle_service_removed("Nonexistent")

        assert callback.call_count == 0


class TestDiscoveryServiceOnServiceStateChange:
    """Tests for _on_service_state_change method."""

    def test_on_service_added(self):
        """Test handling service addition."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "my-service"

        mock_zeroconf = Mock()
        mock_info = Mock()
        mock_info.name = "new-service"
        mock_info.addresses = [b"\x7f\x00\x00\x01"]
        mock_info.port = 9000
        mock_info.properties = {
            b"node_id": b"new-node",
            b"node_type": b"coordinator",
            b"hostname": b"new-host",
        }
        mock_zeroconf.get_service_info.return_value = mock_info

        service._on_service_state_change(mock_zeroconf, "_werender._tcp.local.", "new-service", "Added")

        assert len(service.discovered_nodes) == 1
        assert "new-node" in service.discovered_nodes

    def test_on_service_removed(self):
        """Test handling service removal."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )

        node = NodeInfo(
            name="Node1",
            address="192.168.1.1",
            port=8080,
            node_type="coordinator",
            properties={"node_id": "node-1"},
        )
        service.discovered_nodes["node-1"] = node

        service._on_service_state_change(Mock(), "_werender._tcp.local.", "Node1", "Removed")

        assert "node-1" not in service.discovered_nodes

    def test_on_service_no_info(self):
        """Test handling service with no info."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "my-service"

        mock_zeroconf = Mock()
        mock_zeroconf.get_service_info.return_value = None

        service._on_service_state_change(
            mock_zeroconf, "_werender._tcp.local.", "some-service", "Added"
        )

        assert len(service.discovered_nodes) == 0


class TestDiscoveryServiceHandleServiceAdded:
    """Tests for _handle_service_added method."""

    def test_handle_service_same_type_skipped(self):
        """Test that services of same type are skipped."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "my-service"

        mock_info = Mock()
        mock_info.name = "other-service"
        mock_info.addresses = [b"\x7f\x00\x00\x01"]
        mock_info.port = 9000
        mock_info.properties = {b"node_type": b"worker", b"node_id": b"worker-1"}

        service._handle_service_added(mock_info)

        assert len(service.discovered_nodes) == 0

    def test_handle_service_no_addresses_skipped(self):
        """Test that services without addresses are skipped."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "my-service"

        mock_info = Mock()
        mock_info.name = "other-service"
        mock_info.addresses = []
        mock_info.port = 9000
        mock_info.properties = {b"node_type": b"coordinator", b"node_id": b"coord-1"}

        service._handle_service_added(mock_info)

        assert len(service.discovered_nodes) == 0

    def test_handle_service_same_name_skipped(self):
        """Test that service with same name as self is skipped."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "WeRender-worker-test._werender._tcp.local."

        mock_info = Mock()
        mock_info.name = "WeRender-worker-test._werender._tcp.local."
        mock_info.addresses = [b"\x7f\x00\x00\x01"]
        mock_info.port = 9000
        mock_info.properties = {b"node_type": b"coordinator", b"node_id": b"coord-1"}

        service._handle_service_added(mock_info)

        assert len(service.discovered_nodes) == 0

    def test_handle_service_callback_invoked(self):
        """Test that discovery callback is invoked."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "my-service"

        callback = Mock()
        service.on_discovery = callback

        mock_info = Mock()
        mock_info.name = "other-service"
        mock_info.addresses = [b"\x7f\x00\x00\x01"]
        mock_info.port = 9000
        mock_info.properties = {
            b"node_type": b"coordinator",
            b"node_id": b"coord-1",
            b"hostname": b"coord-host",
        }

        service._handle_service_added(mock_info)

        assert callback.call_count == 1
        assert "coord-1" in service.discovered_nodes

    def test_handle_service_updates_existing(self):
        """Test that existing node is updated (last_seen)."""
        service = DiscoveryService(
            node_type="worker", port=8080, node_id="test", properties={}
        )
        service.service_info = Mock()
        service.service_info.name = "my-service"

        # Add existing node
        node = NodeInfo(
            name="Node1",
            address="192.168.1.1",
            port=9000,
            node_type="coordinator",
            properties={"node_id": "coord-1"},
        )
        service.discovered_nodes["coord-1"] = node

        callback = Mock()
        service.on_discovery = callback

        mock_info = Mock()
        mock_info.name = "Node1"
        mock_info.addresses = [b"\x7f\x00\x00\x01"]
        mock_info.port = 9000
        mock_info.properties = {
            b"node_type": b"coordinator",
            b"node_id": b"coord-1",
            b"hostname": b"coord-host",
        }

        time.sleep(0.01)
        service._handle_service_added(mock_info)

        # Should update last_seen but not call callback
        assert callback.call_count == 0
        assert node.last_seen > service.discovered_nodes["coord-1"].last_seen