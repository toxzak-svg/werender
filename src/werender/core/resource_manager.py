"""Resource management for WeRender."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Set, TYPE_CHECKING
from datetime import datetime, timedelta

from werender.core.job import RenderJob

if TYPE_CHECKING:
    from werender.network.coordinator import WorkerInfo


@dataclass
class WorkerResourceLimits:
    """Resource limits for a worker."""

    max_concurrent_tasks: int = 1
    """Maximum number of tasks a worker can handle simultaneously."""

    max_memory_per_task_gb: Optional[float] = None
    """Maximum memory per task in GB."""

    cpu_utilization_cap: float = 1.0
    """Maximum CPU utilization (0.0-1.0)."""

    gpu_utilization_cap: float = 1.0
    """Maximum GPU utilization (0.0-1.0)."""

    reserved_for_jobs: Set[str] = field(default_factory=set)
    """Job IDs this worker is reserved for."""

    tags: Set[str] = field(default_factory=set)
    """Worker tags/groups."""


@dataclass
class CoordinatorResourceLimits:
    """Resource limits for coordinator."""

    max_concurrent_jobs: int = 10
    """Maximum number of concurrent jobs."""

    min_disk_space_gb: float = 10.0
    """Minimum required disk space in GB."""

    max_network_bandwidth_mbps: Optional[float] = None
    """Maximum network bandwidth in Mbps."""

    disk_space_check_interval: timedelta = timedelta(minutes=5)
    """How often to check disk space."""


class ResourceManager:
    """Manages resource limits and monitoring."""

    def __init__(
        self,
        coordinator_limits: Optional[CoordinatorResourceLimits] = None,
        check_disk_path: Optional[Path] = None,
    ):
        """
        Initialize resource manager.

        Args:
            coordinator_limits: Coordinator resource limits
            check_disk_path: Path to check disk space for (defaults to temp dir)
        """
        self.coordinator_limits = coordinator_limits or CoordinatorResourceLimits()
        self.worker_limits: Dict[str, WorkerResourceLimits] = {}
        self.check_disk_path = check_disk_path or Path.home() / ".werender"
        self.last_disk_check: Optional[datetime] = None

    def set_worker_limits(self, worker_id: str, limits: WorkerResourceLimits) -> None:
        """Set resource limits for a worker."""
        self.worker_limits[worker_id] = limits

    def get_worker_limits(self, worker_id: str) -> WorkerResourceLimits:
        """Get resource limits for a worker (returns defaults if not set)."""
        return self.worker_limits.get(worker_id, WorkerResourceLimits())

    def can_worker_accept_task(
        self,
        worker_id: str,
        worker_info: "WorkerInfo",
        job: RenderJob,
        current_task_count: int = 0,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if worker can accept a new task.

        Args:
            worker_id: Worker identifier
            worker_info: Worker information
            job: Job requesting the task
            current_task_count: Current number of tasks assigned to worker

        Returns:
            Tuple of (can_accept, reason_if_not)
        """
        limits = self.get_worker_limits(worker_id)

        # Check concurrent task limit
        if current_task_count >= limits.max_concurrent_tasks:
            return False, f"Worker at max concurrent tasks ({limits.max_concurrent_tasks})"

        # Check if worker is reserved for specific jobs
        if limits.reserved_for_jobs and job.id not in limits.reserved_for_jobs:
            return False, "Worker is reserved for other jobs"

        # Check memory requirements
        if job.min_memory_gb and limits.max_memory_per_task_gb:
            if job.min_memory_gb > limits.max_memory_per_task_gb:
                return False, f"Insufficient memory limit ({limits.max_memory_per_task_gb}GB < {job.min_memory_gb}GB)"

        return True, None

    def reserve_worker_for_job(self, worker_id: str, job_id: str) -> None:
        """Reserve a worker for a specific job."""
        limits = self.get_worker_limits(worker_id)
        limits.reserved_for_jobs.add(job_id)
        self.worker_limits[worker_id] = limits

    def unreserve_worker(self, worker_id: str, job_id: Optional[str] = None) -> None:
        """Unreserve a worker (optionally for a specific job)."""
        if worker_id not in self.worker_limits:
            return

        limits = self.worker_limits[worker_id]
        if job_id:
            limits.reserved_for_jobs.discard(job_id)
        else:
            limits.reserved_for_jobs.clear()

    def can_coordinator_accept_job(self, current_job_count: int) -> tuple[bool, Optional[str]]:
        """
        Check if coordinator can accept a new job.

        Args:
            current_job_count: Current number of running jobs

        Returns:
            Tuple of (can_accept, reason_if_not)
        """
        if current_job_count >= self.coordinator_limits.max_concurrent_jobs:
            return False, f"Maximum concurrent jobs reached ({self.coordinator_limits.max_concurrent_jobs})"

        # Check disk space
        can_accept, reason = self.check_disk_space()
        if not can_accept:
            return False, reason

        return True, None

    def check_disk_space(self) -> tuple[bool, Optional[str]]:
        """
        Check if there's enough disk space.

        Returns:
            Tuple of (has_space, reason_if_not)
        """
        # Only check periodically to avoid excessive I/O
        now = datetime.now()
        if (
            self.last_disk_check
            and now - self.last_disk_check < self.coordinator_limits.disk_space_check_interval
        ):
            return True, None  # Assume OK if recently checked

        try:
            total, used, free = shutil.disk_usage(self.check_disk_path)
            free_gb = free / (1024 ** 3)

            self.last_disk_check = now

            if free_gb < self.coordinator_limits.min_disk_space_gb:
                return False, f"Insufficient disk space ({free_gb:.1f}GB < {self.coordinator_limits.min_disk_space_gb}GB required)"

            return True, None
        except Exception as e:
            # If we can't check, assume OK but log warning
            print(f"⚠️  Warning: Could not check disk space: {e}")
            return True, None

    def get_disk_space_info(self) -> Dict[str, float]:
        """
        Get current disk space information.

        Returns:
            Dictionary with total, used, and free space in GB
        """
        try:
            total, used, free = shutil.disk_usage(self.check_disk_path)
            return {
                "total_gb": total / (1024 ** 3),
                "used_gb": used / (1024 ** 3),
                "free_gb": free / (1024 ** 3),
            }
        except Exception as e:
            print(f"⚠️  Warning: Could not get disk space info: {e}")
            return {
                "total_gb": 0.0,
                "used_gb": 0.0,
                "free_gb": 0.0,
            }

    def add_worker_tag(self, worker_id: str, tag: str) -> None:
        """Add a tag to a worker."""
        limits = self.get_worker_limits(worker_id)
        limits.tags.add(tag)
        self.worker_limits[worker_id] = limits

    def remove_worker_tag(self, worker_id: str, tag: str) -> None:
        """Remove a tag from a worker."""
        if worker_id not in self.worker_limits:
            return
        limits = self.worker_limits[worker_id]
        limits.tags.discard(tag)

    def get_workers_by_tag(self, tag: str) -> Set[str]:
        """Get all worker IDs with a specific tag."""
        return {
            worker_id
            for worker_id, limits in self.worker_limits.items()
            if tag in limits.tags
        }
