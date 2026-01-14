"""Zeroconf/mDNS discovery for WeRender."""

import socket
import threading
import time
from typing import Callable, Optional

from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

# Service type for WeRender render farm nodes
SERVICE_TYPE = "_werender._tcp.local."
SERVICE_NAME_BASE = "WeRender"


class NodeInfo:
    """Information about a discovered node."""

    def __init__(
        self,
        name: str,
        address: str,
        port: int,
        node_type: str,
        properties: dict,
    ):
        """
        Initialize node info.

        Args:
            name: Service name
            address: IP address
            port: Service port
            node_type: "coordinator" or "worker"
            properties: Additional node properties
        """
        self.name = name
        self.address = address
        self.port = port
        self.node_type = node_type
        self.properties = properties
        self.last_seen = time.time()

    @property
    def node_id(self) -> str:
        """Get the node ID."""
        return self.properties.get("node_id", self.name)

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        return self.properties.get("hostname", "")

    @property
    def blender_version(self) -> str:
        """Get Blender version if available."""
        return self.properties.get("blender_version", "")

    @property
    def cpu_cores(self) -> int:
        """Get CPU core count."""
        return int(self.properties.get("cpu_cores", 0))

    @property
    def gpu_name(self) -> str:
        """Get GPU name if available."""
        return self.properties.get("gpu_name", "")

    def __repr__(self) -> str:
        return (
            f"NodeInfo(name={self.name}, type={self.node_type}, "
            f"address={self.address}:{self.port})"
        )


class DiscoveryService:
    """Service for advertising and discovering WeRender nodes."""

    def __init__(self, node_type: str, port: int, node_id: str, properties: dict):
        """
        Initialize the discovery service.

        Args:
            node_type: "coordinator" or "worker"
            port: Port the service is running on
            node_id: Unique identifier for this node
            properties: Additional properties to advertise
        """
        self.node_type = node_type
        self.port = port
        self.node_id = node_id
        self.properties = properties
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None
        self.browser: Optional[ServiceBrowser] = None
        self.discovered_nodes: dict[str, NodeInfo] = {}
        self.on_discovery: Optional[Callable[[NodeInfo], None]] = None
        self.on_removal: Optional[Callable[[NodeInfo], None]] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start advertising and discovering nodes."""
        self.zeroconf = Zeroconf()

        # Create service info
        service_name = f"{SERVICE_NAME_BASE}-{self.node_type}-{self.node_id}.{SERVICE_TYPE}"

        # Build properties bytes
        properties_dict = {
            "node_id": self.node_id.encode(),
            "node_type": self.node_type.encode(),
            "hostname": socket.gethostname().encode(),
            **{k: str(v).encode() for k, v in self.properties.items()},
        }

        # Get local IP address
        local_ip = self._get_local_ip()

        self.service_info = ServiceInfo(
            SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self.port,
            properties=properties_dict,
        )

        # Register service
        self.zeroconf.register_service(self.service_info)

        # Start browsing for other services
        self.browser = ServiceBrowser(
            self.zeroconf,
            SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )

    def stop(self) -> None:
        """Stop the discovery service."""
        if self.browser:
            self.browser.cancel()
            self.browser = None

        if self.service_info and self.zeroconf:
            self.zeroconf.unregister_service(self.service_info)

        if self.zeroconf:
            self.zeroconf.close()
            self.zeroconf = None

        with self._lock:
            self.discovered_nodes.clear()

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: str,
    ) -> None:
        """
        Handle service state changes.

        Args:
            zeroconf: Zeroconf instance
            service_type: Type of service
            name: Service name
            state_change: "Added" or "Removed"
        """
        if state_change == "Added":
            info = zeroconf.get_service_info(service_type, name)
            if info:
                self._handle_service_added(info)
        elif state_change == "Removed":
            self._handle_service_removed(name)

    def _handle_service_added(self, info: ServiceInfo) -> None:
        """Handle a discovered service."""
        # Skip our own service
        if info.name == self.service_info.name:
            return

        # Parse properties
        properties = {}
        if info.properties:
            for key, value in info.properties.items():
                try:
                    properties[key.decode()] = value.decode()
                except Exception:
                    pass

        # Skip nodes of same type (workers don't need to discover workers)
        if properties.get("node_type") == self.node_type:
            return

        # Get address
        if not info.addresses:
            return
        address = socket.inet_ntoa(info.addresses[0])

        # Create node info
        node_type = properties.get("node_type", "unknown")
        node_info = NodeInfo(
            name=info.name,
            address=address,
            port=info.port,
            node_type=node_type,
            properties=properties,
        )

        with self._lock:
            # Check if we already know about this node
            if node_info.node_id in self.discovered_nodes:
                # Update last seen time
                self.discovered_nodes[node_info.node_id].last_seen = time.time()
                return

            # Add new node
            self.discovered_nodes[node_info.node_id] = node_info

        # Notify callback
        if self.on_discovery:
            self.on_discovery(node_info)

    def _handle_service_removed(self, name: str) -> None:
        """Handle a removed service."""
        with self._lock:
            # Find the node to remove
            node_to_remove = None
            for node_id, node_info in self.discovered_nodes.items():
                if node_info.name == name:
                    node_to_remove = node_info
                    break

            if node_to_remove:
                del self.discovered_nodes[node_to_remove]

        # Notify callback
        if node_to_remove and self.on_removal:
            self.on_removal(node_to_remove)

    def get_nodes(self, node_type: Optional[str] = None) -> list[NodeInfo]:
        """
        Get discovered nodes.

        Args:
            node_type: Filter by node type ("coordinator" or "worker")

        Returns:
            List of discovered nodes
        """
        with self._lock:
            nodes = list(self.discovered_nodes.values())
            if node_type:
                nodes = [n for n in nodes if n.node_type == node_type]
            return nodes

    def _get_local_ip(self) -> str:
        """
        Get the local IP address.

        Returns:
            Local IP address
        """
        try:
            # Create a socket to determine the local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"