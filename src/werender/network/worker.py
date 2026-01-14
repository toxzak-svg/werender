"""Worker node for WeRender."""

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
from websockets.client import connect as websocket_connect

from werender.core.blender import BlenderRenderer, RenderResult
from werender.network.discovery import DiscoveryService, NodeInfo


class WorkerNode:
    """A worker node that renders frames for a coordinator."""

    def __init__(
        self,
        name: Optional[str] = None,
        port: int = 8421,
    ):
        """
        Initialize the worker node.

        Args:
            name: Custom worker name (defaults to hostname)
            port: Port to run worker service on
        """
        import socket
        import uuid

        self.name = name or socket.gethostname()
        self.port = port
        self.node_id = str(uuid.uuid4())[:8]

        # Get system specs
        from werender.utils.system import get_system_specs
        self.specs = get_system_specs()

        # Get Blender version
        try:
            self.blender_version = BlenderRenderer().get_version()
        except Exception:
            self.blender_version = ""

        # Discovery service
        self.discovery = DiscoveryService(
            node_type="worker",
            port=self.port,
            node_id=self.node_id,
            properties={
                "name": self.name,
                "hostname": socket.gethostname(),
                "cpu_cores": self.specs.cpu_cores,
                "cpu_threads": self.specs.cpu_threads,
                "ram_gb": self.specs.ram_gb,
                "gpu_name": self.specs.gpu_name or "None",
                "gpu_vram_gb": self.specs.gpu_vram_gb or 0,
                "blender_version": self.blender_version,
            },
        )

        # Worker state
        self.coordinator: Optional[NodeInfo] = None
        self.blender = BlenderRenderer()
        self.temp_dir = Path(tempfile.gettempdir()) / "werender" / self.node_id
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.is_running = False

        # Async client for HTTP requests
        self.http_client: Optional[httpx.AsyncClient] = None

    def start(self) -> None:
        """Start the worker node."""
        print(f"🎬 WeRender - Worker Node")
        print("=" * 50)
        print(f"📛 Name: {self.name}")
        print(f"🆔 Node ID: {self.node_id}")
        print(f"🖥️  CPU: {self.specs.cpu_cores} cores")
        print(f"💾 RAM: {self.specs.ram_gb} GB")
        if self.specs.gpu_name:
            print(f"🎮 GPU: {self.specs.gpu_name}")
        print(f"🎨 Blender: {self.blender_version or 'Not found'}")
        print()
        print("🔍 Scanning for coordinator...")

        # Set up discovery callbacks
        self.discovery.on_discovery = self._on_coordinator_discovered
        self.discovery.on_removal = self._on_coordinator_removed

        # Start discovery
        self.discovery.start()

        # Run async worker loop
        asyncio.run(self._worker_loop())

    def stop(self) -> None:
        """Stop the worker node."""
        print("🛑 Shutting down worker...")
        self.is_running = False
        self.discovery.stop()

    async def _worker_loop(self) -> None:
        """Main worker loop."""
        self.is_running = True
        self.http_client = httpx.AsyncClient(timeout=30.0)

        while self.is_running:
            try:
                if self.coordinator:
                    await self._request_and_render_task()
                else:
                    # No coordinator, wait a bit
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ Error in worker loop: {e}")
                await asyncio.sleep(5)

        # Cleanup
        if self.http_client:
            await self.http_client.aclose()

    def _on_coordinator_discovered(self, node: NodeInfo) -> None:
        """Handle coordinator discovery."""
        print(f"✅ Found coordinator: {node.hostname} ({node.address}:{node.port})")
        self.coordinator = node

    def _on_coordinator_removed(self, node: NodeInfo) -> None:
        """Handle coordinator removal."""
        if self.coordinator and self.coordinator.node_id == node.node_id:
            print(f"⚠️  Coordinator {node.hostname} disconnected")
            self.coordinator = None

    async def _request_and_render_task(self) -> None:
        """Request a task from coordinator and render it."""
        if not self.coordinator:
            return

        base_url = f"http://{self.coordinator.address}:{self.coordinator.port}"

        try:
            # Request a task
            async with self.http_client.stream(
                "GET",
                f"{base_url}/api/tasks/request",
                params={
                    "worker_id": self.node_id,
                    "worker_name": self.name,
                    "cpu_cores": self.specs.cpu_cores,
                    "gpu_name": self.specs.gpu_name or "None",
                },
            ) as response:
                if response.status_code == 204:
                    # No tasks available
                    await asyncio.sleep(2)
                    return

                if response.status_code != 200:
                    print(f"❌ Failed to request task: {response.status_code}")
                    await asyncio.sleep(5)
                    return

                task_data = await response.json()

            print(f"\n📦 Received task: Frame {task_data['frame_number']}")

            # Download blend file if needed
            blend_path = await self._download_blend_file(
                base_url,
                task_data["job_id"],
                task_data["blend_file_hash"],
            )

            if not blend_path:
                print(f"❌ Failed to download blend file")
                await self._report_task_failure(task_data, "Failed to download blend file")
                return

            # Render the frame
            output_dir = self.temp_dir / task_data["job_id"]
            output_dir.mkdir(exist_ok=True)

            result = self.blender.render_frame(
                blend_path,
                task_data["frame_number"],
                output_dir,
            )

            if result.success:
                print(f"✅ Rendered frame {result.frame} in {result.render_time:.1f}s")

                # Upload result
                await self._upload_result(
                    base_url,
                    task_data,
                    result.output_file,
                    result.render_time,
                )
            else:
                print(f"❌ Render failed: {result.error_message}")
                await self._report_task_failure(task_data, result.error_message or "Render failed")

        except httpx.ConnectError:
            print(f"❌ Cannot connect to coordinator")
            self.coordinator = None
        except Exception as e:
            print(f"❌ Error rendering task: {e}")

    async def _download_blend_file(
        self,
        base_url: str,
        job_id: str,
        file_hash: str,
    ) -> Optional[Path]:
        """
        Download blend file from coordinator.

        Args:
            base_url: Coordinator base URL
            job_id: Job ID
            file_hash: Hash of the blend file

        Returns:
            Path to downloaded blend file, or None if failed
        """
        # Check if we already have the file
        blend_dir = self.temp_dir / "blend_files"
        blend_dir.mkdir(exist_ok=True)
        local_path = blend_dir / f"{file_hash}.blend"

        if local_path.exists():
            return local_path

        # Download file
        try:
            async with self.http_client.stream(
                "GET",
                f"{base_url}/api/jobs/{job_id}/blend",
            ) as response:
                if response.status_code != 200:
                    print(f"❌ Failed to download blend file: {response.status_code}")
                    return None

                # Stream download to avoid memory issues
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes(8192):
                        f.write(chunk)

            print(f"📥 Downloaded blend file: {file_hash}")
            return local_path

        except Exception as e:
            print(f"❌ Error downloading blend file: {e}")
            if local_path.exists():
                local_path.unlink()
            return None

    async def _upload_result(
        self,
        base_url: str,
        task_data: dict,
        output_file: Path,
        render_time: float,
    ) -> None:
        """
        Upload rendered frame to coordinator.

        Args:
            base_url: Coordinator base URL
            task_data: Task data
            output_file: Path to rendered output
            render_time: Time taken to render
        """
        if not output_file or not output_file.exists():
            print(f"❌ Output file not found: {output_file}")
            return

        try:
            with open(output_file, "rb") as f:
                files = {"output": (output_file.name, f, "image/png")}
                data = {
                    "render_time": str(render_time),
                }

                response = await self.http_client.post(
                    f"{base_url}/api/tasks/{task_data['id']}/complete",
                    data=data,
                    files=files,
                )

            if response.status_code == 200:
                print(f"📤 Uploaded result for frame {task_data['frame_number']}")
            else:
                print(f"❌ Failed to upload result: {response.status_code}")

        except Exception as e:
            print(f"❌ Error uploading result: {e}")

    async def _report_task_failure(self, task_data: dict, error: str) -> None:
        """
        Report task failure to coordinator.

        Args:
            task_data: Task data
            error: Error message
        """
        if not self.coordinator:
            return

        base_url = f"http://{self.coordinator.address}:{self.coordinator.port}"

        try:
            await self.http_client.post(
                f"{base_url}/api/tasks/{task_data['id']}/fail",
                json={"error": error},
            )
        except Exception as e:
            print(f"❌ Failed to report task failure: {e}")