"""Tests for job and task models."""

import pytest

from werender.core.job import FrameTask, JobStatus, RenderJob, TaskStatus


class TestFrameTask:
    """Tests for FrameTask model."""

    def test_create_task(self):
        """Test creating a new frame task."""
        task = FrameTask(frame_number=42)
        assert task.frame_number == 42
        assert task.status == TaskStatus.PENDING
        assert task.assigned_worker is None

    def test_assign_task(self):
        """Test assigning a task to a worker."""
        task = FrameTask(frame_number=1)
        task.assign_to("worker-001")

        assert task.status == TaskStatus.ASSIGNED
        assert task.assigned_worker == "worker-001"
        assert task.assigned_at is not None

    def test_start_rendering(self):
        """Test marking task as rendering."""
        task = FrameTask(frame_number=1)
        task.assign_to("worker-001")
        task.start_rendering()

        assert task.status == TaskStatus.RENDERING
        assert task.started_at is not None

    def test_complete_task(self):
        """Test completing a task."""
        from pathlib import Path

        task = FrameTask(frame_number=1)
        task.assign_to("worker-001")
        task.start_rendering()
        task.complete(Path("/output/0001.png"))

        assert task.status == TaskStatus.COMPLETED
        assert task.output_file == Path("/output/0001.png")
        assert task.completed_at is not None

    def test_fail_task(self):
        """Test failing a task."""
        task = FrameTask(frame_number=1)
        task.assign_to("worker-001")
        task.start_rendering()
        task.fail("Out of memory")

        assert task.status == TaskStatus.FAILED
        assert task.error_message == "Out of memory"

    def test_reset_task(self):
        """Test resetting a failed task for re-queue."""
        task = FrameTask(frame_number=1)
        task.assign_to("worker-001")
        task.fail("Connection lost")
        task.reset()

        assert task.status == TaskStatus.PENDING
        assert task.assigned_worker is None
        assert task.error_message is None


class TestRenderJob:
    """Tests for RenderJob model."""

    def test_create_job(self):
        """Test creating a render job."""
        from pathlib import Path

        job = RenderJob(
            blend_file=Path("/project/test.blend"),
            frame_start=1,
            frame_end=10,
        )

        assert job.frame_start == 1
        assert job.frame_end == 10
        assert job.total_frames == 10
        assert job.status == JobStatus.PENDING

    def test_create_tasks(self):
        """Test creating frame tasks for a job."""
        from pathlib import Path

        job = RenderJob(
            blend_file=Path("/project/test.blend"),
            frame_start=1,
            frame_end=5,
        )
        job.create_tasks()

        assert len(job.tasks) == 5
        assert job.tasks[0].frame_number == 1
        assert job.tasks[4].frame_number == 5

    def test_progress_tracking(self):
        """Test progress percentage calculation."""
        from pathlib import Path

        job = RenderJob(
            blend_file=Path("/project/test.blend"),
            frame_start=1,
            frame_end=10,
        )
        job.create_tasks()

        # Initially 0%
        assert job.progress_percent == 0.0

        # Complete 5 tasks
        for task in job.tasks[:5]:
            task.complete(Path(f"/output/{task.frame_number:04d}.png"))

        assert job.progress_percent == 50.0
        assert job.completed_frames == 5

    def test_get_next_task(self):
        """Test getting the next pending task."""
        from pathlib import Path

        job = RenderJob(
            blend_file=Path("/project/test.blend"),
            frame_start=1,
            frame_end=3,
        )
        job.create_tasks()

        # First pending task is frame 1
        next_task = job.get_next_task()
        assert next_task is not None
        assert next_task.frame_number == 1

        # Assign frame 1
        next_task.assign_to("worker-001")

        # Now next pending is frame 2
        next_task = job.get_next_task()
        assert next_task is not None
        assert next_task.frame_number == 2

    def test_job_completion(self):
        """Test job completion detection."""
        from pathlib import Path

        job = RenderJob(
            blend_file=Path("/project/test.blend"),
            frame_start=1,
            frame_end=3,
        )
        job.create_tasks()
        job.start()

        # Complete all tasks
        for task in job.tasks:
            task.complete(Path(f"/output/{task.frame_number:04d}.png"))

        job.check_completion()
        assert job.status == JobStatus.COMPLETED
        assert job.completed_at is not None
