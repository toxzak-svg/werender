"""Job and task models for WeRender."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Set
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a render task."""

    PENDING = "pending"
    """Task is waiting to be assigned."""

    ASSIGNED = "assigned"
    """Task has been assigned to a worker."""

    RENDERING = "rendering"
    """Task is currently being rendered."""

    COMPLETED = "completed"
    """Task has been successfully completed."""

    FAILED = "failed"
    """Task failed to render."""


class FrameTask(BaseModel):
    """A single frame render task."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    """Unique task identifier."""

    frame_number: int
    """Frame number to render."""

    status: TaskStatus = TaskStatus.PENDING
    """Current status of the task."""

    assigned_worker: Optional[str] = None
    """ID of worker assigned to this task."""

    assigned_at: Optional[datetime] = None
    """When the task was assigned."""

    started_at: Optional[datetime] = None
    """When rendering started."""

    completed_at: Optional[datetime] = None
    """When rendering completed."""

    output_file: Optional[Path] = None
    """Path to the output file (on coordinator)."""

    error_message: Optional[str] = None
    """Error message if task failed."""

    render_time_seconds: Optional[float] = None
    """Time taken to render the frame."""

    def assign_to(self, worker_id: str) -> None:
        """Assign this task to a worker."""
        self.status = TaskStatus.ASSIGNED
        self.assigned_worker = worker_id
        self.assigned_at = datetime.now()

    def start_rendering(self) -> None:
        """Mark task as rendering."""
        self.status = TaskStatus.RENDERING
        self.started_at = datetime.now()

    def complete(self, output_file: Path) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now()
        self.output_file = output_file
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.render_time_seconds = delta.total_seconds()

    def fail(self, error: str) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error

    def reset(self) -> None:
        """Reset task to pending state (for re-queue)."""
        self.status = TaskStatus.PENDING
        self.assigned_worker = None
        self.assigned_at = None
        self.started_at = None
        self.completed_at = None
        self.error_message = None


class JobStatus(str, Enum):
    """Status of a render job."""

    PENDING = "pending"
    """Job is waiting to start."""

    RUNNING = "running"
    """Job is actively being rendered."""

    PAUSED = "paused"
    """Job has been paused."""

    COMPLETED = "completed"
    """All frames have been rendered."""

    FAILED = "failed"
    """Job failed (too many task failures)."""

    CANCELLED = "cancelled"
    """Job was cancelled by user."""


class RenderJob(BaseModel):
    """A complete render job containing multiple frame tasks."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    """Unique job identifier."""

    name: str = ""
    """Human-readable job name (defaults to blend file name)."""

    blend_file: Path
    """Path to the .blend file on the coordinator."""

    packed_file: Optional[Path] = None
    """Path to the packed .blend file (with embedded assets)."""

    frame_start: int
    """First frame to render."""

    frame_end: int
    """Last frame to render."""

    blender_version: str = ""
    """Required Blender version for rendering."""

    output_directory: Path = Path("./output")
    """Directory to store rendered frames."""

    status: JobStatus = JobStatus.PENDING
    """Current status of the job."""

    tasks: list[FrameTask] = Field(default_factory=list)
    """List of frame tasks for this job."""

    created_at: datetime = Field(default_factory=datetime.now)
    """When the job was created."""

    started_at: Optional[datetime] = None
    """When the job started rendering."""

    completed_at: Optional[datetime] = None
    """When the job finished."""

    # Enhanced job management features
    priority: int = Field(default=5, ge=1, le=10)
    """Job priority (1-10, higher is more urgent)."""

    requires_gpu: bool = False
    """Whether this job requires GPU acceleration."""

    min_memory_gb: Optional[float] = None
    """Minimum memory requirement in GB."""

    worker_tags: Set[str] = Field(default_factory=set)
    """Required worker tags/groups."""

    depends_on: Set[str] = Field(default_factory=set)
    """Job IDs that must complete before this job starts."""

    scheduled_time: Optional[datetime] = None
    """When to start this job (for scheduled jobs)."""

    def create_tasks(self) -> None:
        """Create frame tasks for all frames in the range."""
        self.tasks = [
            FrameTask(frame_number=frame)
            for frame in range(self.frame_start, self.frame_end + 1)
        ]

    @property
    def total_frames(self) -> int:
        """Total number of frames to render."""
        return self.frame_end - self.frame_start + 1

    @property
    def completed_frames(self) -> int:
        """Number of completed frames."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def progress_percent(self) -> float:
        """Render progress as a percentage."""
        if not self.tasks:
            return 0.0
        return (self.completed_frames / len(self.tasks)) * 100

    @property
    def pending_tasks(self) -> list[FrameTask]:
        """Get all pending tasks."""
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    @property
    def average_render_time(self) -> Optional[float]:
        """Average render time for completed frames."""
        completed = [
            t.render_time_seconds
            for t in self.tasks
            if t.status == TaskStatus.COMPLETED and t.render_time_seconds
        ]
        if not completed:
            return None
        return sum(completed) / len(completed)

    def get_next_task(self) -> Optional[FrameTask]:
        """Get the next pending task, if any."""
        pending = self.pending_tasks
        return pending[0] if pending else None

    def start(self) -> None:
        """Mark job as running."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now()

    def pause(self) -> None:
        """Pause the job."""
        self.status = JobStatus.PAUSED

    def resume(self) -> None:
        """Resume a paused job."""
        self.status = JobStatus.RUNNING

    def check_completion(self) -> None:
        """Check if job is complete and update status."""
        if all(t.status == TaskStatus.COMPLETED for t in self.tasks):
            self.status = JobStatus.COMPLETED
            self.completed_at = datetime.now()
