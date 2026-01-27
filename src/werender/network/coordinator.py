"""Coordinator server for WeRender."""

import asyncio
import hashlib
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from werender.core.blender import BlenderRenderer
from werender.core.job import RenderJob, TaskStatus, JobStatus
from werender.network.discovery import DiscoveryService, NodeInfo
from werender.network.sync import SyncManager
from werender.network.auth import AuthManager, get_api_key_dependency
from werender.network.security import BlendFileValidator, RateLimiter
from werender.scheduler import TaskScheduler, SchedulingStrategy, ChunkingStrategy, JobRequirements
from werender.core.job_templates import JobTemplateManager, JobExporter, JobPreset
from werender.core.resource_manager import ResourceManager
from werender.core.database import Database, JobStatus as DBJobStatus, TaskStatus as DBTaskStatus



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

        # Sync Manager with asset cache
        self.config_dir = Path.home() / ".werender"
        self.config_dir.mkdir(exist_ok=True)
        self.sync_manager = SyncManager(
            config_path=self.config_dir / "werender.json",
            addons_dir=self.config_dir / "addons",
            cache_db_path=self.config_dir / "asset_cache.db",
        )

        # Authentication Manager
        self.auth_manager = AuthManager(self.config_dir)
        
        # Security components
        self.rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

        # Task Scheduler
        self.scheduler = TaskScheduler(
            strategy=SchedulingStrategy.HYBRID,
            chunking=ChunkingStrategy.SINGLE_FRAME,
        )

        # Job Template Manager
        self.template_manager = JobTemplateManager(
            templates_dir=self.config_dir / "templates"
        )

        # Resource Manager
        self.resource_manager = ResourceManager(
            check_disk_path=self.config_dir
        )

        # Database for persistence
        self.database = Database(self.config_dir / "werender.db")
        
        # Load persisted jobs and workers on startup
        self._load_persisted_data()

        # Setup FastAPI app
        self.app = FastAPI(title="WeRender Coordinator")
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""
        self.app.add_event_handler("startup", self._on_startup)
        self.app.add_event_handler("shutdown", self._on_shutdown)

        # Create authentication dependencies
        worker_auth = get_api_key_dependency(self.auth_manager, "worker")
        coordinator_auth = get_api_key_dependency(self.auth_manager, "coordinator")

        # Worker endpoints (require worker authentication)
        self.app.get("/api/tasks/request", dependencies=[Depends(worker_auth)])(self._api_request_task)
        self.app.post("/api/tasks/{task_id}/complete", dependencies=[Depends(worker_auth)])(self._api_complete_task)
        self.app.post("/api/tasks/{task_id}/fail", dependencies=[Depends(worker_auth)])(self._api_fail_task)
        self.app.get("/api/jobs/{job_id}/blend", dependencies=[Depends(worker_auth)])(self._api_get_blend_file)

        # Job management endpoints (require coordinator authentication - CRITICAL SECURITY FIX)
        self.app.post("/api/jobs/create", dependencies=[Depends(coordinator_auth)])(self._api_create_job)
        self.app.get("/api/jobs", dependencies=[Depends(coordinator_auth)])(self._api_list_jobs)
        self.app.get("/api/jobs/{job_id}", dependencies=[Depends(coordinator_auth)])(self._api_get_job)
        self.app.patch("/api/jobs/{job_id}", dependencies=[Depends(coordinator_auth)])(self._api_update_job)
        self.app.post("/api/jobs/{job_id}/start", dependencies=[Depends(coordinator_auth)])(self._api_start_job)
        self.app.post("/api/jobs/{job_id}/pause", dependencies=[Depends(coordinator_auth)])(self._api_pause_job)
        self.app.post("/api/jobs/{job_id}/resume", dependencies=[Depends(coordinator_auth)])(self._api_resume_job)
        self.app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(coordinator_auth)])(self._api_cancel_job)
        self.app.post("/api/jobs/{job_id}/reload_blend", dependencies=[Depends(coordinator_auth)])(self._api_reload_blend)
        
        # Global job control endpoints
        self.app.post("/api/jobs/pause_all", dependencies=[Depends(coordinator_auth)])(self._api_pause_all_jobs)

        # Worker management endpoints (require coordinator authentication)
        self.app.get("/api/workers", dependencies=[Depends(coordinator_auth)])(self._api_list_workers)

        # Job template endpoints
        self.app.get("/api/templates", dependencies=[Depends(coordinator_auth)])(self._api_list_templates)
        self.app.get("/api/templates/{template_id}", dependencies=[Depends(coordinator_auth)])(self._api_get_template)
        self.app.post("/api/templates", dependencies=[Depends(coordinator_auth)])(self._api_create_template)
        self.app.delete("/api/templates/{template_id}", dependencies=[Depends(coordinator_auth)])(self._api_delete_template)
        self.app.post("/api/templates/preset/{preset}", dependencies=[Depends(coordinator_auth)])(self._api_create_preset_template)

        # Job export/import endpoints
        self.app.get("/api/jobs/{job_id}/export", dependencies=[Depends(coordinator_auth)])(self._api_export_job)
        self.app.post("/api/jobs/import", dependencies=[Depends(coordinator_auth)])(self._api_import_job)

        # Resource management endpoints
        self.app.get("/api/resources/disk", dependencies=[Depends(coordinator_auth)])(self._api_get_disk_space)
        self.app.get("/api/resources/workers/{worker_id}/limits", dependencies=[Depends(coordinator_auth)])(self._api_get_worker_limits)
        self.app.post("/api/resources/workers/{worker_id}/limits", dependencies=[Depends(coordinator_auth)])(self._api_set_worker_limits)
        self.app.post("/api/resources/workers/{worker_id}/reserve", dependencies=[Depends(coordinator_auth)])(self._api_reserve_worker)

        # Sync endpoints (require coordinator authentication - SECURITY FIX)
        self.app.get("/api/sync/manifest", dependencies=[Depends(worker_auth)])(self._api_get_sync_manifest)
        self.app.get("/api/sync/settings", dependencies=[Depends(worker_auth)])(self._api_get_settings)
        self.app.get("/api/sync/addons", dependencies=[Depends(worker_auth)])(self._api_list_addons)
        self.app.get("/api/sync/addons/{addon_name}/download", dependencies=[Depends(worker_auth)])(self._api_download_addon)

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
        # Save current state to database
        self._save_persisted_data()
        self.discovery.stop()

    def _load_persisted_data(self) -> None:
        """Load persisted jobs and workers from database."""
        try:
            # Load workers
            workers = self.database.list_workers(online_only=False)
            for worker_data in workers:
                worker_info = WorkerInfo(
                    worker_id=worker_data["id"],
                    worker_name=worker_data["name"],
                    cpu_cores=worker_data.get("cpu_cores", 0),
                    gpu_name=worker_data.get("gpu_name", "None"),
                    last_seen=time.time(),
                )
                self.workers[worker_data["id"]] = worker_info
                # Update online status
                self.database.update_worker_online_status(worker_data["id"], False)

            # Load recent jobs (last 100)
            jobs = self.database.list_jobs(limit=100)
            for job_data in jobs:
                # Only load completed/failed jobs for history
                # Active jobs should be recreated from current state
                if job_data["status"] in (DBJobStatus.COMPLETED, DBJobStatus.FAILED, DBJobStatus.CANCELLED):
                    # Create job object from database data
                    try:
                        job = RenderJob(
                            id=job_data["id"],
                            name=job_data["name"],
                            blend_file=Path(job_data["blend_file_path"]) if job_data.get("blend_file_path") else None,
                            frame_start=job_data["frame_start"],
                            frame_end=job_data["frame_end"],
                        )
                        job.status = JobStatus(job_data["status"])
                        job.created_at = datetime.fromisoformat(job_data["created_at"]) if job_data.get("created_at") else datetime.now()
                        
                        # Load tasks
                        tasks = self.database.get_job_tasks(job_data["id"])
                        for task_data in tasks:
                            from werender.core.job import FrameTask
                            task = FrameTask(
                                id=task_data["id"],
                                frame_number=task_data["frame_number"],
                            )
                            task.status = TaskStatus(task_data["status"])
                            if task_data.get("output_file_path"):
                                task.output_file = Path(task_data["output_file_path"])
                            if task_data.get("render_time_seconds"):
                                task.render_time_seconds = task_data["render_time_seconds"]
                            job.tasks.append(task)
                        
                        self.jobs[job.id] = job
                    except Exception as e:
                        print(f"⚠️  Failed to load job {job_data['id']}: {e}")

        except Exception as e:
            print(f"⚠️  Error loading persisted data: {e}")

    def _save_persisted_data(self) -> None:
        """Save current jobs and workers to database."""
        try:
            # Save all workers
            for worker_id, worker_info in self.workers.items():
                worker_data = {
                    "id": worker_id,
                    "name": worker_info.worker_name,
                    "cpu_cores": worker_info.cpu_cores,
                    "gpu_name": worker_info.gpu_name,
                    "is_online": True,
                    "last_seen": datetime.now(),
                    "current_task_id": worker_info.current_task_id,
                }
                self.database.save_worker(worker_data)

            # Save all jobs
            for job_id, job in self.jobs.items():
                job_data = {
                    "id": job.id,
                    "name": job.name,
                    "blend_file_path": str(job.blend_file) if job.blend_file else None,
                    "packed_file_path": str(job.packed_file) if job.packed_file else None,
                    "blend_file_hash": job.blend_file_hash,
                    "frame_start": job.frame_start,
                    "frame_end": job.frame_end,
                    "status": job.status.value,
                    "priority": getattr(job, "priority", 0),
                    "created_at": job.created_at.isoformat() if job.created_at else datetime.now().isoformat(),
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "blender_version": job.blender_version,
                    "output_dir": str(job.output_dir) if job.output_dir else None,
                }
                self.database.save_job(job_data)

                # Save all tasks
                for task in job.tasks:
                    task_data = {
                        "id": task.id,
                        "job_id": job.id,
                        "frame_number": task.frame_number,
                        "status": task.status.value,
                        "assigned_worker": task.assigned_worker,
                        "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
                        "started_at": task.started_at.isoformat() if task.started_at else None,
                        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                        "render_time_seconds": task.render_time_seconds,
                        "output_file_path": str(task.output_file) if task.output_file else None,
                        "error_message": task.error_message,
                    }
                    self.database.save_task(task_data)

        except Exception as e:
            print(f"⚠️  Error saving persisted data: {e}")

    def _save_job_to_db(self, job: RenderJob) -> None:
        """Save a single job to database."""
        try:
            job_data = {
                "id": job.id,
                "name": job.name,
                "blend_file_path": str(job.blend_file) if job.blend_file else None,
                "packed_file_path": str(job.packed_file) if job.packed_file else None,
                "blend_file_hash": job.blend_file_hash,
                "frame_start": job.frame_start,
                "frame_end": job.frame_end,
                "status": job.status.value,
                "priority": getattr(job, "priority", 0),
                "created_at": job.created_at.isoformat() if job.created_at else datetime.now().isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "blender_version": job.blender_version,
                "output_dir": str(job.output_dir) if job.output_dir else None,
            }
            self.database.save_job(job_data)
        except Exception as e:
            print(f"⚠️  Error saving job to database: {e}")

    def _save_worker_to_db(self, worker_info: WorkerInfo) -> None:
        """Save a single worker to database."""
        try:
            worker_data = {
                "id": worker_info.worker_id,
                "name": worker_info.worker_name,
                "cpu_cores": worker_info.cpu_cores,
                "gpu_name": worker_info.gpu_name,
                "is_online": True,
                "last_seen": datetime.now(),
                "current_task_id": worker_info.current_task_id,
            }
            self.database.save_worker(worker_data)
        except Exception as e:
            print(f"⚠️  Error saving worker to database: {e}")

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
        worker_info = WorkerInfo(
            worker_id=worker_id,
            worker_name=worker_name,
            cpu_cores=cpu_cores,
            gpu_name=gpu_name,
            last_seen=current_time,
            current_task_id=None,
        )
        self.workers[worker_id] = worker_info
        self._save_worker_to_db(worker_info)

        # Sort jobs by priority (higher priority first)
        sorted_jobs = sorted(
            [j for j in self.jobs.values() if j.status == "running"],
            key=lambda j: j.priority,
            reverse=True,
        )

        # Count current tasks for this worker
        worker_task_count = 1 if worker_info.current_task_id else 0

        # Look for the next pending task across all running jobs (prioritized)
        for job in sorted_jobs:
            task = job.get_next_task()
            if not task:
                continue

            # Check resource limits
            can_accept, reason = self.resource_manager.can_worker_accept_task(
                worker_id=worker_id,
                worker_info=worker_info,
                job=job,
                current_task_count=worker_task_count,
            )
            if not can_accept:
                continue  # Try next job

            # Create job requirements from job properties
            job_requirements = JobRequirements(
                job_id=job.id,
                priority=job.priority,
                requires_gpu=job.requires_gpu,
                min_memory_gb=job.min_memory_gb,
                required_blender_version=job.blender_version if job.blender_version else None,
                worker_tags=job.worker_tags,
            )

            # Use scheduler to select the best worker
            selected_worker = self.scheduler.select_worker(
                task=task,
                job=job,
                workers=self.workers,
                job_requirements=job_requirements,
            )

            if selected_worker == worker_id:
                # This worker was selected! Assign the task
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

        # No tasks available for this worker - worker should try again later
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

        # Save task to database
        try:
            task_data = {
                "id": task.id,
                "job_id": job.id,
                "frame_number": task.frame_number,
                "status": task.status.value,
                "assigned_worker": task.assigned_worker,
                "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "render_time_seconds": task.render_time_seconds,
                "output_file_path": str(task.output_file) if task.output_file else None,
            }
            self.database.save_task(task_data)
        except Exception as e:
            print(f"⚠️  Error saving task to database: {e}")

        # Update scheduler statistics
        if task.assigned_worker and task.render_time_seconds:
            self.scheduler.update_worker_stats(
                task.assigned_worker,
                task.render_time_seconds,
            )

        # Free up worker
        if task.assigned_worker in self.workers:
            self.workers[task.assigned_worker].current_task_id = None
            self._save_worker_to_db(self.workers[task.assigned_worker])

        # Check if job is complete
        job.check_completion()

        if job.status == "completed":
            print(f"🎉 Job {job.name} completed!")
            # Update job status in database
            self.database.update_job_status(
                job.id,
                DBJobStatus.COMPLETED,
                completed_at=datetime.now(),
            )

        # Save job status update
        self._save_job_to_db(job)

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

        # Save task failure to database
        try:
            task_data = {
                "id": task.id,
                "job_id": job.id,
                "frame_number": task.frame_number,
                "status": task.status.value,
                "assigned_worker": task.assigned_worker,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "error_message": task.error_message,
            }
            self.database.save_task(task_data)
        except Exception as e:
            print(f"⚠️  Error saving task failure to database: {e}")

        # Free up worker
        if task.assigned_worker in self.workers:
            self.workers[task.assigned_worker].current_task_id = None
            self._save_worker_to_db(self.workers[task.assigned_worker])

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
        # Sanitize filename to prevent path traversal
        safe_filename = BlendFileValidator.sanitize_filename(file.filename or "unnamed.blend")
        
        # Save uploaded blend file
        temp_dir = Path(tempfile.gettempdir()) / "werender" / "jobs"
        temp_dir.mkdir(parents=True, exist_ok=True)

        blend_path = temp_dir / safe_filename
        with open(blend_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        # Validate the .blend file for security
        is_valid, error_msg = BlendFileValidator.validate_blend_file(blend_path)
        if not is_valid:
            blend_path.unlink()  # Delete the invalid file
            raise HTTPException(
                status_code=400,
                detail=f"Invalid .blend file: {error_msg}"
            )

        # Check if coordinator can accept new job
        current_job_count = sum(1 for j in self.jobs.values() if j.status == "running")
        can_accept, reason = self.resource_manager.can_coordinator_accept_job(current_job_count)
        if not can_accept:
            blend_path.unlink()  # Clean up
            raise HTTPException(status_code=503, detail=f"Cannot accept job: {reason}")

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
        self._save_job_to_db(job)
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

        if job.status == "running":
            return {"status": "already_running"}

        # Check job dependencies
        can_start, reason = self._check_job_dependencies(job)
        if not can_start:
            raise HTTPException(status_code=400, detail=f"Cannot start job: {reason}")

        # Check scheduled time
        if job.scheduled_time and job.scheduled_time > datetime.now():
            raise HTTPException(
                status_code=400,
                detail=f"Job is scheduled for {job.scheduled_time.isoformat()}"
            )

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

    async def _api_pause_all_jobs(self) -> dict:
        """API: Pause all running jobs."""
        paused_count = 0
        for job in self.jobs.values():
            if job.status == JobStatus.RUNNING:
                job.pause()
                paused_count += 1
                print(f"⏸️  Job {job.name} paused")
        
        await self._broadcast_update("jobs")
        return {"status": "success", "paused_count": paused_count}

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

        # Save new blend file with sanitized filename
        safe_filename = BlendFileValidator.sanitize_filename(blend.filename)
        temp_dir = Path(tempfile.gettempdir()) / "werender" / "jobs"
        temp_dir.mkdir(parents=True, exist_ok=True)

        new_blend_path = temp_dir / safe_filename
        with open(new_blend_path, "wb") as f:
            shutil.copyfileobj(blend.file, f)
        
        # Validate the .blend file for security
        is_valid, error_msg = BlendFileValidator.validate_blend_file(new_blend_path)
        if not is_valid:
            new_blend_path.unlink()  # Delete the invalid file
            raise HTTPException(
                status_code=400,
                detail=f"Invalid .blend file: {error_msg}"
            )
        
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
        result = []
        for w in self.workers.values():
            # Find the current frame if worker has a task
            current_frame = None
            if w.current_task_id:
                for job in self.jobs.values():
                    for task in job.tasks:
                        if task.id == w.current_task_id:
                            current_frame = task.frame_number
                            break
                    if current_frame is not None:
                        break
            
            # Get system stats if available (optional - workers can send this)
            worker_data = {
                "worker_id": w.worker_id,
                "worker_name": w.worker_name,
                "cpu_cores": w.cpu_cores,
                "gpu_name": w.gpu_name,
                "current_task_id": w.current_task_id,
                "current_frame": current_frame,
                "last_seen": w.last_seen,
            }
            result.append(worker_data)
        return result



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

    # ========== Template Management Endpoints ==========

    async def _api_list_templates(self) -> list[dict]:
        """API: List all job templates."""
        templates = self.template_manager.list_templates()
        return [t.model_dump() for t in templates]

    async def _api_get_template(self, template_id: str) -> dict:
        """API: Get a specific template."""
        template = self.template_manager.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        return template.model_dump()

    async def _api_create_template(self, template_data: dict) -> dict:
        """API: Create a new template."""
        from werender.core.job_templates import JobTemplate
        template = JobTemplate(**template_data)
        self.template_manager.save_template(template)
        return template.model_dump()

    async def _api_delete_template(self, template_id: str) -> dict:
        """API: Delete a template."""
        success = self.template_manager.delete_template(template_id)
        if not success:
            raise HTTPException(status_code=404, detail="Template not found")
        return {"status": "deleted"}

    async def _api_create_preset_template(self, preset: str) -> dict:
        """API: Create template from preset."""
        try:
            preset_enum = JobPreset(preset)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid preset: {preset}")
        
        template = self.template_manager.create_from_preset(preset_enum)
        return template.model_dump()

    # ========== Job Export/Import Endpoints ==========

    async def _api_export_job(self, job_id: str, include_tasks: bool = False) -> dict:
        """API: Export job configuration."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobExporter.export_job(job, include_tasks=include_tasks)

    async def _api_import_job(
        self,
        file: UploadFile = File(...),
        blend_file: Optional[UploadFile] = File(None),
    ) -> dict:
        """API: Import job from configuration."""
        import json
        
        # Read job config
        config_data = await file.read()
        config = json.loads(config_data.decode())

        # If blend file provided, use it; otherwise require existing file path
        if blend_file:
            safe_filename = BlendFileValidator.sanitize_filename(blend_file.filename or "unnamed.blend")
            temp_dir = Path(tempfile.gettempdir()) / "werender" / "jobs"
            temp_dir.mkdir(parents=True, exist_ok=True)
            blend_path = temp_dir / safe_filename
            
            with open(blend_path, "wb") as f:
                shutil.copyfileobj(blend_file.file, f)
            
            # Validate blend file
            is_valid, error_msg = BlendFileValidator.validate_blend_file(blend_path)
            if not is_valid:
                blend_path.unlink()
                raise HTTPException(status_code=400, detail=f"Invalid .blend file: {error_msg}")
        else:
            # Try to use path from config
            blend_path = Path(config.get("blend_file_path", ""))
            if not blend_path.exists():
                raise HTTPException(status_code=400, detail="Blend file not found and not provided")

        # Create job from config
        job = JobExporter.create_job_from_config(config, blend_path)
        
        # Pack resources
        try:
            renderer = BlenderRenderer()
            job.packed_file = renderer.pack_resources(blend_path)
            job.blender_version = renderer.get_version()
        except Exception as e:
            print(f"⚠️  Warning: Failed to pack resources: {e}")

        self.jobs[job.id] = job
        self._save_job_to_db(job)
        await self._broadcast_update("jobs")
        
        return {"job_id": job.id, "status": "imported"}

    # ========== Resource Management Endpoints ==========

    async def _api_get_disk_space(self) -> dict:
        """API: Get disk space information."""
        return self.resource_manager.get_disk_space_info()

    async def _api_get_worker_limits(self, worker_id: str) -> dict:
        """API: Get worker resource limits."""
        if worker_id not in self.workers:
            raise HTTPException(status_code=404, detail="Worker not found")
        
        limits = self.resource_manager.get_worker_limits(worker_id)
        return {
            "max_concurrent_tasks": limits.max_concurrent_tasks,
            "max_memory_per_task_gb": limits.max_memory_per_task_gb,
            "cpu_utilization_cap": limits.cpu_utilization_cap,
            "gpu_utilization_cap": limits.gpu_utilization_cap,
            "reserved_for_jobs": list(limits.reserved_for_jobs),
            "tags": list(limits.tags),
        }

    async def _api_set_worker_limits(self, worker_id: str, limits_data: dict) -> dict:
        """API: Set worker resource limits."""
        if worker_id not in self.workers:
            raise HTTPException(status_code=404, detail="Worker not found")
        
        from werender.core.resource_manager import WorkerResourceLimits
        
        limits = WorkerResourceLimits(
            max_concurrent_tasks=limits_data.get("max_concurrent_tasks", 1),
            max_memory_per_task_gb=limits_data.get("max_memory_per_task_gb"),
            cpu_utilization_cap=limits_data.get("cpu_utilization_cap", 1.0),
            gpu_utilization_cap=limits_data.get("gpu_utilization_cap", 1.0),
            reserved_for_jobs=set(limits_data.get("reserved_for_jobs", [])),
            tags=set(limits_data.get("tags", [])),
        )
        
        self.resource_manager.set_worker_limits(worker_id, limits)
        return {"status": "updated"}

    async def _api_reserve_worker(self, worker_id: str, job_id: str = Query(...)) -> dict:
        """API: Reserve a worker for a specific job."""
        if worker_id not in self.workers:
            raise HTTPException(status_code=404, detail="Worker not found")
        if job_id not in self.jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        
        self.resource_manager.reserve_worker_for_job(worker_id, job_id)
        return {"status": "reserved"}

    # ========== Job Dependency Checking ==========

    def _check_job_dependencies(self, job: RenderJob) -> tuple[bool, Optional[str]]:
        """
        Check if job dependencies are satisfied.

        Returns:
            Tuple of (can_start, reason_if_not)
        """
        if not job.depends_on:
            return True, None

        for dep_id in job.depends_on:
            dep_job = self.jobs.get(dep_id)
            if not dep_job:
                return False, f"Dependency job {dep_id} not found"
            
            if dep_job.status != JobStatus.COMPLETED:
                return False, f"Dependency job {dep_id} is not completed (status: {dep_job.status})"

        return True, None

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