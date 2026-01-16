"""Coordinator server for WeRender."""

import asyncio
import hashlib
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from werender.core.blender import BlenderRenderer
from werender.core.job import RenderJob, TaskStatus
from werender.network.discovery import DiscoveryService, NodeInfo
from werender.network.sync import SyncManager
from werender.network.auth import AuthManager, get_api_key_dependency



class WorkerInfo(BaseModel):
    """Information about a connected worker."""

    worker_id: str
    worker_name: str
    cpu_cores: int
    gpu_name: str
    last_seen: float
    current_task_id: Optional[str] = None


class UpdateJobRequest(BaseModel):
    """Request to update job properties."""

    start_frame: Optional[int] = None
    end_frame: Optional[int] = None


class CoordinatorServer:
    """Coordinator server that manages jobs and distributes tasks."""

    def __init__(self, port: int = 8420):
        """
        Initialize the coordinator server.

        Args:
            port: Port to run the server on
        """
        import socket
        import uuid

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

        # Storage
        self.jobs: dict[str, RenderJob] = {}
        self.workers: dict[str, WorkerInfo] = {}
        self.blender_path: Optional[Path] = None

        # WebSocket connections
        self.websocket_connections: list[WebSocket] = []

        # Discovery service
        self.discovery = DiscoveryService(
            node_type="coordinator",
            port=self.port,
            node_id=self.node_id,
            properties={
                "hostname": socket.gethostname(),
                "cpu_cores": self.specs.cpu_cores,
                "blender_version": self.blender_version,
            },
        )

        # Sync Manager
        self.config_dir = Path.home() / ".werender"
        self.config_dir.mkdir(exist_ok=True)
        self.sync_manager = SyncManager(
            config_path=self.config_dir / "werender.json",
            addons_dir=self.config_dir / "addons",
        )

        # Authentication Manager
        self.auth_manager = AuthManager(self.config_dir)

        # Setup FastAPI app
        self.app = FastAPI(title="WeRender Coordinator")
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""
        self.app.add_event_handler("startup", self._on_startup)
        self.app.add_event_handler("shutdown", self._on_shutdown)

        # Create authentication dependencies
        worker_auth = get_api_key_dependency(self.auth_manager, "worker")

        # Worker endpoints (require worker authentication)
        self.app.get("/api/tasks/request", dependencies=[Depends(worker_auth)])(self._api_request_task)
        self.app.post("/api/tasks/{task_id}/complete", dependencies=[Depends(worker_auth)])(self._api_complete_task)
        self.app.post("/api/tasks/{task_id}/fail", dependencies=[Depends(worker_auth)])(self._api_fail_task)
        self.app.get("/api/jobs/{job_id}/blend", dependencies=[Depends(worker_auth)])(self._api_get_blend_file)

        # Job management endpoints
        self.app.post("/api/jobs/create")(self._api_create_job)
        self.app.get("/api/jobs")(self._api_list_jobs)
        self.app.get("/api/jobs/{job_id}")(self._api_get_job)
        self.app.patch("/api/jobs/{job_id}")(self._api_update_job)
        self.app.post("/api/jobs/{job_id}/start")(self._api_start_job)
        self.app.post("/api/jobs/{job_id}/pause")(self._api_pause_job)
        self.app.post("/api/jobs/{job_id}/resume")(self._api_resume_job)
        self.app.post("/api/jobs/{job_id}/cancel")(self._api_cancel_job)
        self.app.post("/api/jobs/{job_id}/reload_blend")(self._api_reload_blend)

        # Worker management endpoints
        self.app.get("/api/workers")(self._api_list_workers)

        # Sync endpoints
        self.app.get("/api/sync/manifest")(self._api_get_sync_manifest)
        self.app.get("/api/sync/settings")(self._api_get_settings)
        self.app.get("/api/sync/addons")(self._api_list_addons)
        self.app.get("/api/sync/addons/{addon_name}/download")(self._api_download_addon)

        # WebSocket endpoint
        self.app.websocket("/ws")(self._websocket_endpoint)

        # Serve static files (dashboard)
        dashboard_dir = Path(__file__).parent.parent / "dashboard"
        if dashboard_dir.exists():
            self.app.mount("/", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    async def _on_startup(self) -> None:
        """Handle startup event - initialize services and background tasks."""
        # Start mDNS discovery to find workers on the network
        self.discovery.start()
        self.discovery.on_discovery = self._on_worker_discovered
        self.discovery.on_removal = self._on_worker_removed

        # Launch background tasks for monitoring and updates
        # Health check: monitors worker connectivity and re-queues tasks from dead workers
        # Broadcast: sends periodic updates to dashboard clients
        asyncio.create_task(self._health_check_loop())
        asyncio.create_task(self._broadcast_updates_loop())

    async def _on_shutdown(self) -> None:
        """Handle shutdown event."""
        self.discovery.stop()

    async def _health_check_loop(self) -> None:
        """
        Monitor worker health and handle timeouts.
        
        Workers must send heartbeat requests every 30 seconds. If a worker
        doesn't communicate within this window, we assume it's dead and
        re-queue any assigned task.
        """
        while True:
            await asyncio.sleep(5)
            current_time = time.time()

            # Identify workers that haven't sent a heartbeat recently
            stale_workers = []
            for worker_id, worker_info in self.workers.items():
                if current_time - worker_info.last_seen > 30:  # 30 second timeout
                    stale_workers.append(worker_id)

            # Handle stale workers: re-queue their tasks and remove them
            for worker_id in stale_workers:
                worker = self.workers[worker_id]
                
                # If this worker had an active task, it needs to be re-queued
                if worker.current_task_id:
                    task_found = False
                    for job in self.jobs.values():
                        for task in job.tasks:
                            if task.id == worker.current_task_id:
                                print(f"⚠️  Worker {worker.worker_name} timed out, re-queueing task {task.id}")
                                task.reset()
                                task_found = True
                                break
                        if task_found:
                            break

                del self.workers[worker_id]
                print(f"⚠️  Worker {worker.worker_name} removed (timeout)")

            # Update dashboard with the new worker list
            await self._broadcast_update("workers")

    async def _broadcast_updates_loop(self) -> None:
        """Periodically broadcast updates to WebSocket clients."""
        while True:
            await asyncio.sleep(2)
            await self._broadcast_update("all")

    async def _on_worker_discovered(self, node: NodeInfo) -> None:
        """
        Called when a new worker is discovered via mDNS.
        
        Note: This doesn't mean the worker is authenticated yet. The worker
        must make an authenticated API request before it can receive tasks.
        """
        print(f"✅ Worker discovered: {node.hostname} ({node.address}:{node.port})")
        await self._broadcast_update("workers")

    async def _on_worker_removed(self, node: NodeInfo) -> None:
        """
        Called when mDNS detects a worker is no longer advertising itself.
        
        This happens when a worker shuts down gracefully or disconnects from
        the network. Any task the worker was working on gets re-queued.
        """
        # Find all workers matching this hostname (in case of duplicates)
        to_remove = []
        for worker_id, worker_info in self.workers.items():
            if worker_info.worker_name == node.hostname:
                to_remove.append(worker_id)

        # Clean up each disconnected worker
        for worker_id in to_remove:
            worker = self.workers[worker_id]
            
            # Re-queue any task this worker was working on
            if worker.current_task_id:
                task_found = False
                for job in self.jobs.values():
                    for task in job.tasks:
                        if task.id == worker.current_task_id:
                            print(f"⚠️  Worker {worker.worker_name} disconnected, re-queueing task {task.id}")
                            task.reset()
                            task_found = True
                            break
                    if task_found:
                        break

            del self.workers[worker_id]
            print(f"⚠️  Worker {worker.worker_name} removed (disconnected)")

        await self._broadcast_update("workers")

    # ========== API Endpoints ==========

    async def _api_request_task(
        self,
        worker_id: str,
        worker_name: str,
        cpu_cores: int,
        gpu_name: str,
    ) -> dict:
        """
        Worker requests a new task to render.
        
        This endpoint requires worker authentication. The worker provides its
        specs which we use for scheduling decisions in the future (currently
        just for display).
        
        Returns 204 (No Content) if no tasks are available.
        """
        current_time = time.time()

        # Register or update this worker's information
        # The worker_id should be unique per worker instance
        if worker_id not in self.workers:
            print(f"📝 New worker registered: {worker_name} (ID: {worker_id})")
        self.workers[worker_id] = WorkerInfo(
            worker_id=worker_id,
            worker_name=worker_name,
            cpu_cores=cpu_cores,
            gpu_name=gpu_name,
            last_seen=current_time,
            current_task_id=None,
        )

        # Look for the next pending task across all running jobs
        for job in self.jobs.values():
            # Only assign tasks from jobs that are currently running
            if job.status not in ["running"]:
                continue

            task = job.get_next_task()
            if task:
                # Found a task! Assign it to this worker
                task.assign_to(worker_id)
                task.start_rendering()
                self.workers[worker_id].current_task_id = task.id

                # Return task details so the worker knows what to render
                return {
                    "id": task.id,
                    "job_id": job.id,
                    "frame_number": task.frame_number,
                    "blend_file_hash": self._get_blend_file_hash(job),
                }

        # No tasks available - worker should try again later
        raise HTTPException(status_code=204)

    async def _api_complete_task(
        self,
        task_id: str,
        output: UploadFile = File(...),
        render_time: str = Form(...),
    ) -> dict:
        """API: Upload completed task result."""
        # Find the task
        task = None
        job = None
        for j in self.jobs.values():
            for t in j.tasks:
                if t.id == task_id:
                    task = t
                    job = j
                    break
            if task:
                break

        if not task or not job:
            raise HTTPException(status_code=404, detail="Task not found")

        # Save output file
        output_path = job.output_directory / f"{task.frame_number:04d}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "wb") as f:
            shutil.copyfileobj(output.file, f)

        # Mark task as complete
        task.complete(output_path)

        # Free up worker
        if task.assigned_worker in self.workers:
            self.workers[task.assigned_worker].current_task_id = None

        # Check if job is complete
        job.check_completion()

        if job.status == "completed":
            print(f"🎉 Job {job.name} completed!")

        await self._broadcast_update("jobs")
        return {"status": "success"}

    async def _api_fail_task(self, task_id: str, error: dict) -> dict:
        """API: Report task failure."""
        # Find the task
        task = None
        job = None
        for j in self.jobs.values():
            for t in j.tasks:
                if t.id == task_id:
                    task = t
                    job = j
                    break
            if task:
                break

        if not task or not job:
            raise HTTPException(status_code=404, detail="Task not found")

        # Mark task as failed
        task.fail(error.get("error", "Unknown error"))

        # Free up worker
        if task.assigned_worker in self.workers:
            self.workers[task.assigned_worker].current_task_id = None

        await self._broadcast_update("jobs")
        return {"status": "success"}

    async def _api_get_blend_file(self, job_id: str) -> FileResponse:
        """API: Download blend file for a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Use packed file if available, otherwise original
        blend_file = job.packed_file or job.blend_file
        if not blend_file.exists():
            raise HTTPException(status_code=404, detail="Blend file not found")

        return FileResponse(
            blend_file,
            media_type="application/octet-stream",
            filename=blend_file.name,
        )

    async def _api_create_job(
        self,
        file: UploadFile = File(...),
        frame_start: int = Form(...),
        frame_end: int = Form(...),
        name: str = Form(""),
    ) -> dict:
        """API: Create a new render job."""
        # Save uploaded blend file
        temp_dir = Path(tempfile.gettempdir()) / "werender" / "jobs"
        temp_dir.mkdir(parents=True, exist_ok=True)

        blend_path = temp_dir / file.filename
        with open(blend_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Create job
        job = RenderJob(
            name=name or file.filename,
            blend_file=blend_path,
            frame_start=frame_start,
            frame_end=frame_end,
        )
        job.create_tasks()

        # Pack resources
        print(f"📦 Packing resources for job {job.id}...")
        try:
            renderer = BlenderRenderer()
            job.packed_file = renderer.pack_resources(blend_path)
            job.blender_version = renderer.get_version()
            print(f"✅ Resources packed for job {job.id}")
        except Exception as e:
            print(f"⚠️  Warning: Failed to pack resources: {e}")

        self.jobs[job.id] = job
        print(f"✅ Job created: {job.name} (frames {frame_start}-{frame_end})")

        await self._broadcast_update("jobs")
        return {"job_id": job.id, "status": "pending"}

    async def _api_list_jobs(self) -> list[dict]:
        """API: List all jobs."""
        return [
            {
                "id": job.id,
                "name": job.name,
                "status": job.status,
                "progress": job.progress_percent,
                "total_frames": job.total_frames,
                "completed_frames": job.completed_frames,
                "frame_start": job.frame_start,  # BUG FIX: Missing frame_start
                "frame_end": job.frame_end,      # BUG FIX: Missing frame_end
            }
            for job in self.jobs.values()
        ]

    async def _api_get_job(self, job_id: str) -> dict:
        """API: Get job details."""
        print(f"[DEBUG] _api_get_job called with job_id={job_id}")
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        result = {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "progress": job.progress_percent,
            "total_frames": job.total_frames,
            "completed_frames": job.completed_frames,
            "frame_start": job.frame_start,  # BUG FIX: Missing frame_start
            "frame_end": job.frame_end,      # BUG FIX: Missing frame_end
            "tasks": [
                {
                    "id": t.id,
                    "frame_number": t.frame_number,
                    "status": t.status,
                }
                for t in job.tasks
            ],
        }
        print(f"[DEBUG] _api_get_job returning: {result}")
        return result

    async def _api_start_job(self, job_id: str) -> dict:
        """API: Start a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.start()
        print(f"▶️  Job {job.name} started")
        await self._broadcast_update("jobs")
        return {"status": "running"}

    async def _api_pause_job(self, job_id: str) -> dict:
        """API: Pause a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.pause()
        print(f"⏸️  Job {job.name} paused")
        await self._broadcast_update("jobs")
        return {"status": "paused"}

    async def _api_resume_job(self, job_id: str) -> dict:
        """API: Resume a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.resume()
        print(f"▶️  Job {job.name} resumed")
        await self._broadcast_update("jobs")
        return {"status": "running"}

    async def _api_cancel_job(self, job_id: str) -> dict:
        """API: Cancel a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Reset all pending tasks
        for task in job.tasks:
            if task.status != TaskStatus.COMPLETED:
                task.reset()

        job.status = "cancelled"
        print(f"❌ Job {job.name} cancelled")
        await self._broadcast_update("jobs")
        return {"status": "cancelled"}

    async def _api_update_job(self, job_id: str, request: UpdateJobRequest) -> dict:
        """API: Update job properties (frame range)."""
        print(f"[DEBUG] _api_update_job called with job_id={job_id}, request={request}")
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Check if job is in a state that allows updates
        if job.status in ["running"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot update job while it is running. Pause the job first."
            )

        # Get new frame values (use existing values if not provided)
        new_start = request.start_frame if request.start_frame is not None else job.frame_start
        new_end = request.end_frame if request.end_frame is not None else job.frame_end

        # Validate frame range
        if new_start > new_end:
            raise HTTPException(
                status_code=400,
                detail="start_frame must be less than or equal to end_frame"
            )

        # Update job frame range
        job.frame_start = new_start
        job.frame_end = new_end

        # Regenerate tasks for new frame range
        job.create_tasks()

        # Reset job status if it was completed
        if job.status == "completed":
            job.status = "pending"

        print(f"📝 Job {job.name} updated: frames {new_start}-{new_end}")
        await self._broadcast_update("jobs")

        return {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "progress": job.progress_percent,
            "total_frames": job.total_frames,
            "completed_frames": job.completed_frames,
            "frame_start": job.frame_start,
            "frame_end": job.frame_end,
        }

    async def _api_reload_blend(
        self,
        job_id: str,
        blend: UploadFile = File(...),
    ) -> dict:
        """API: Re-upload and replace a job's blend file."""
        print(f"[DEBUG] _api_reload_blend called with job_id={job_id}, blend.filename={blend.filename}")
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Validate file extension
        if not blend.filename or not blend.filename.lower().endswith(".blend"):
            raise HTTPException(
                status_code=400,
                detail="File must be a .blend file"
            )

        # Check if job is in a state that allows updates
        if job.status in ["running"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot reload blend file while job is running. Pause the job first."
            )

        # Save new blend file
        temp_dir = Path(tempfile.gettempdir()) / "werender" / "jobs"
        temp_dir.mkdir(parents=True, exist_ok=True)

        new_blend_path = temp_dir / blend.filename
        with open(new_blend_path, "wb") as f:
            shutil.copyfileobj(blend.file, f)

        # Replace existing blend file
        job.blend_file = new_blend_path

        # Pack resources
        print(f"📦 Packing resources for job {job.id}...")
        try:
            renderer = BlenderRenderer()
            job.packed_file = renderer.pack_resources(new_blend_path)
            job.blender_version = renderer.get_version()
            print(f"✅ Resources packed for job {job.id}")
        except Exception as e:
            print(f"⚠️  Warning: Failed to pack resources: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to pack resources: {e}"
            )

        # Reset job status and tasks
        job.status = "pending"
        job.create_tasks()

        print(f"🔄 Blend file reloaded for job {job.name}")
        await self._broadcast_update("jobs")

        return {
            "status": "success",
            "message": "Blend file reloaded successfully",
            "job_id": job.id,
        }

    async def _api_list_workers(self) -> list[dict]:
        """API: List all connected workers."""
        return [
            {
                "worker_id": w.worker_id,
                "worker_name": w.worker_name,
                "cpu_cores": w.cpu_cores,
                "gpu_name": w.gpu_name,
                "current_task_id": w.current_task_id,
                "last_seen": w.last_seen,
            }
            for w in self.workers.values()
        ]



    async def _api_get_sync_manifest(self) -> dict:
        """API: Get synchronization manifest."""
        return self.sync_manager.get_manifest()

    async def _api_get_settings(self) -> dict:
        """API: Get global settings."""
        return self.sync_manager.get_settings()

    async def _api_list_addons(self) -> list[dict]:
        """API: List available add-ons."""
        return self.sync_manager.get_addons_list()

    async def _api_download_addon(self, addon_name: str) -> FileResponse:
        """API: Download an add-on zip."""
        addons = self.sync_manager.get_addons_list()
        target_addon = next((a for a in addons if a["name"] == addon_name), None)
        
        if not target_addon:
             raise HTTPException(status_code=404, detail="Add-on not found")
        
        addon_path = self.sync_manager.addons_dir / target_addon["filename"]
        if not addon_path.exists():
            raise HTTPException(status_code=404, detail="Add-on file missing")

        return FileResponse(
            addon_path,
            media_type="application/zip",
            filename=addon_path.name,
        )

    async def _websocket_endpoint(self, websocket: WebSocket) -> None:

        """WebSocket endpoint for real-time updates."""
        await websocket.accept()
        self.websocket_connections.append(websocket)

        try:
            while True:
                # Keep connection alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            self.websocket_connections.remove(websocket)

    async def _broadcast_update(self, update_type: str) -> None:
        """Broadcast update to all connected WebSocket clients."""
        if not self.websocket_connections:
            return

        data = {"type": update_type}

        if update_type in ["jobs", "all"]:
            data["jobs"] = await self._api_list_jobs()

        if update_type in ["workers", "all"]:
            data["workers"] = await self._api_list_workers()

        # Send to all connected clients
        disconnected = []
        for websocket in self.websocket_connections:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)

        # Remove disconnected clients
        for ws in disconnected:
            if ws in self.websocket_connections:
                self.websocket_connections.remove(ws)

    def _get_blend_file_hash(self, job: RenderJob) -> str:
        """Get hash of blend file."""
        blend_file = job.packed_file or job.blend_file
        hash_md5 = hashlib.md5()
        with open(blend_file, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def run(self) -> None:
        """Run the coordinator server."""
        print(f"🎬 WeRender - Coordinator Mode")
        print("=" * 50)
        print(f"🖥️  Hostname: {self.specs.hostname}")
        print(f"🆔 Node ID: {self.node_id}")
        print(f"🖥️  CPU: {self.specs.cpu_cores} cores")
        print(f"💾 RAM: {self.specs.ram_gb} GB")
        print(f"🎨 Blender: {self.blender_version or 'Not found'}")
        print()
        print(f"🌐 Server running on http://0.0.0.0:{self.port}")
        print(f"📡 Advertising via mDNS")
        print(f"🔒 Authentication enabled - workers require API key")
        print()

        # Print authentication setup instructions
        self.auth_manager.print_setup_instructions()

        uvicorn.run(self.app, host="0.0.0.0", port=self.port)