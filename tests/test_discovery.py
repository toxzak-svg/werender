
import pytest
import time
from unittest.mock import MagicMock, patch
from werender.network.discovery import NodeInfo, DiscoveryService

def test_node_info_parsing():
    """Test parsing of NodeInfo properties."""
    properties = {
        "node_id": "test-node-1",
        "cpu_cores": "16",
        "gpu_name": "Test GPU",
        "blender_version": "4.0.0"
    }
    
    info = NodeInfo(
        name="Test Node",
        address="192.168.1.10",
        port=8080,
        node_type="worker",
        properties=properties
    )
    
    assert info.node_id == "test-node-1"
    assert info.cpu_cores == 16
    assert info.gpu_name == "Test GPU"
    assert info.blender_version == "4.0.0"

def test_discovery_service_property_decoding(caplog):
    """Test that discovery service handles malformed properties gracefully."""
    service = DiscoveryService("worker", 8080, "test-id", {})
    
    # Create a mock ServiceInfo with a property that fails decoding
    mock_info = MagicMock()
    mock_info.name = "other-service"
    # Create a mock dictionary that raises error on iteration or access if needed,
    # but the code iterates and decodes.
    # We'll rely on the fact that values come in as bytes usually.
    # Let's simulate a bad byte sequence that fails .decode()
    
    bad_bytes = b'\xff\xff' # Invalid UTF-8
    
    mock_info.properties = {
        b'good_key': b'good_value',
        b'bad_key': bad_bytes
    }
    mock_info.addresses = [b'\x7f\x00\x00\x01'] # 127.0.0.1
    mock_info.port = 9090
    
    # We mock _handle_service_added's internal logic mostly by invoking it directly
    # or by testing the private method if possible/easy.
    # The method is _handle_service_added.
    
    with patch("werender.network.discovery.socket.inet_ntoa", return_value="127.0.0.1"):
        service._handle_service_added(mock_info)
        
    # Check that we logged the error but didn't crash
    assert "Failed to decode property" in caplog.text
    
    # Verify the node was added with the good property
    # Note: The code creates a new properties dict. 
    # 'good_key' should be there. 'bad_key' should be missing.
    # We need to access the discovered node to check.
    
    # Wait for lock
    with service._lock:
        nodes = list(service.discovered_nodes.values())
        assert len(nodes) == 1
        node = nodes[0]
        assert node.properties['good_key'] == 'good_value'
        assert 'bad_key' not in node.properties
