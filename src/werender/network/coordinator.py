"""Coordinator server for WeRender."""

import asyncio
import hashlib
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from werender.core.blender import BlenderRenderer
from werender.core.job import RenderJob, TaskStatus
from werender.network.discovery import DiscoveryService, NodeInfo


class WorkerInfo(BaseModel):
    """Information about a connected worker."""

    worker_id: str
    worker_name: str
    cpu_cores: int
    gpu_name: str
    last_seen: float
    current_task_id: Optional[str] = None


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

        # Setup FastAPI app
        self.app = FastAPI(title="WeRender Coordinator")
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""
        self.app.add_event_handler("startup", self._on_startup)
        self.app.add_event_handler("shutdown", self._on_shutdown)

        # Worker endpoints
        self.app.get("/api/tasks/request")(self._api_request_task)
        self.app.post("/api/tasks/{task_id}/complete")(self._api_complete_task)
        self.app.post("/api/tasks/{task_id}/fail")(self._api_fail_task)
        self.app.get("/api/jobs/{job_id}/blend")(self._api_get_blend_file)

        # Job management endpoints
        self.app.post("/api/jobs/create")(self._api_create_job)
        self.app.get("/api/jobs")(self._api_list_jobs)
        self.app.get("/api/jobs/{job_id}")(self._api_get_job)
        self.app.post("/api/jobs/{job_id}/start")(self._api_start_job)
        self.app.post("/api/jobs/{job_id}/pause")(self._api_pause_job)
        self.app.post("/api/jobs/{job_id}/resume")(self._api_resume_job)
        self.app.post("/api/jobs/{job_id}/cancel")(self._api_cancel_job)

        # Worker management endpoints
        self.app.get("/api/workers")(self._api_list_workers)

    async def _on_startup(self) -> None:
        """Handle startup event."""
        self.discovery.start()
        self.discovery.on_discovery = self._on_worker_discovered
        self.discovery.on_removal = self._on_worker_removed

        # Start worker health check task
        asyncio.create_task(self._health_check_loop())

    async def _on_shutdown(self) -> None:
        """Handle shutdown event."""
        self.discovery.stop()

    async def _health_check_loop(self) -> None:
        """Periodically check worker health."""
        while True:
            await asyncio.sleep(5)
            current_time = time.time()

            # Check for stale workers
            stale_workers = []
            for worker_id, worker_info in self.workers.items():
                if current_time - worker_info.last_seen > 30:  # 30 second timeout
                    stale_workers.append(worker_id)

            # Re-queue tasks from stale workers
            for worker_id in stale_workers:
                worker = self.workers[worker_id]
                if worker.current_task_id:
                    for job in self.jobs.values():
                        for task in job.tasks:
                            if task.id == worker.current_task_id:
                                print(f"⚠️  Worker {worker.worker_name} timed out, re-queueing task {task.id}")
                                task.reset()

                del self.workers[worker_id]
                print(f"⚠️  Worker {worker.worker_name} removed (timeout)")

    def _on_worker_discovered(self, node: NodeInfo) -> None:
        """Handle worker discovery."""
        print(f"✅ Worker discovered: {node.hostname} ({node.address}:{node.port})")

    def _on_worker_removed(self, node: NodeInfo) -> None:
        """Handle worker removal."""
        # Find and remove worker
        to_remove = []
        for worker_id, worker_info in self.workers.items():
            if worker_info.worker_name == node.hostname:
                to_remove.append(worker_id)

        for worker_id in to_remove:
            worker = self.workers[worker_id]
            if worker.current_task_id:
                # Re-queue the task
                for job in self.jobs.values():
                    for task in job.tasks:
                        if task.id == worker.current_task_id:
                            print(f"⚠️  Worker {worker.worker_name} disconnected, re-queueing task {task.id}")
                            task.reset()

            del self.workers[worker_id]
            print(f"⚠️  Worker {worker.worker_name} removed (disconnected)")

    # ========== API Endpoints ==========

    async def _api_request_task(
        self,
        worker_id: str,
        worker_name: str,
        cpu_cores: int,
        gpu_name: str,
    ) -> dict:
        """API: Request a task to render."""
        current_time = time.time()

        # Update or create worker info
        if worker_id not in self.workers:
            print(f"📝 New worker: {worker_name}")
        self.workers[worker_id] = WorkerInfo(
            worker_id=worker_id,
            worker_name=worker_name,
            cpu_cores=cpu_cores,
            gpu_name=gpu_name,
            last_seen=current_time,
            current_task_id=None,
        )

        # Find next pending task
        for job in self.jobs.values():
            if job.status not in ["running"]:
                continue

            task = job.get_next_task()
            if task:
                # Assign task to worker
                task.assign_to(worker_id)
                task.start_rendering()
                self.workers[worker_id].current_task_id = task.id

                return {
                    "id": task.id,
                    "job_id": job.id,
                    "frame_number": task.frame_number,
                    "blend_file_hash": self._get_blend_file_hash(job),
                }

        # No tasks available
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
            }
            for job in self.jobs.values()
        ]

    async def _api_get_job(self, job_id: str) -> dict:
        """API: Get job details."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "progress": job.progress_percent,
            "total_frames": job.total_frames,
            "completed_frames": job.completed_frames,
            "tasks": [
                {
                    "id": t.id,
                    "frame_number": t.frame_number,
                    "status": t.status,
                }
                for t in job.tasks
            ],
        }

    async def _api_start_job(self, job_id: str) -> dict:
        """API: Start a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.start()
        print(f"▶️  Job {job.name} started")
        return {"status": "running"}

    async def _api_pause_job(self, job_id: str) -> dict:
        """API: Pause a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.pause()
        print(f"⏸️  Job {job.name} paused")
        return {"status": "paused"}

    async def _api_resume_job(self, job_id: str) -> dict:
        """API: Resume a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.resume()
        print(f"▶️  Job {job.name} resumed")
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
        return {"status": "cancelled"}

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
        print()

        uvicorn.run(self.app, host="0.0.0.0", port=self.port)