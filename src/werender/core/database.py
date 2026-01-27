"""Database persistence module for WeRender.

This module provides SQLite-based persistence for:
- Job history and metadata
- Persistent worker registry
- Frame-level tracking and statistics
"""

import json
import sqlite3
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Any
from contextlib import contextmanager


class JobStatus(str, Enum):
    """Job status enumeration."""

    PENDING = "pending"
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskStatus(str, Enum):
    """Task status enumeration."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class Database:
    """SQLite database for WeRender persistence."""

    def __init__(self, db_path: Path):
        """
        Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Get database connection with proper transaction handling."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    blend_file_path TEXT,
                    packed_file_path TEXT,
                    blend_file_hash TEXT,
                    frame_start INTEGER NOT NULL,
                    frame_end INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    created_at TIMESTAMP NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    blender_version TEXT,
                    metadata TEXT,
                    output_dir TEXT
                )
            """)

            # Tasks (frames) table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    frame_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    assigned_worker TEXT,
                    assigned_at TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    render_time_seconds REAL,
                    output_file_path TEXT,
                    error_message TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    UNIQUE(job_id, frame_number)
                )
            """)

            # Workers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    hostname TEXT,
                    address TEXT,
                    port INTEGER,
                    cpu_cores INTEGER,
                    cpu_threads INTEGER,
                    ram_gb REAL,
                    gpu_name TEXT,
                    gpu_vram_gb REAL,
                    blender_version TEXT,
                    last_seen TIMESTAMP,
                    is_online BOOLEAN DEFAULT 0,
                    current_task_id TEXT,
                    metadata TEXT
                )
            """)

            # Worker statistics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS worker_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    cpu_usage REAL,
                    ram_usage REAL,
                    gpu_usage REAL,
                    tasks_completed INTEGER DEFAULT 0,
                    tasks_failed INTEGER DEFAULT 0,
                    FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE
                )
            """)

            # Job statistics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    frames_completed INTEGER DEFAULT 0,
                    frames_total INTEGER NOT NULL,
                    frames_failed INTEGER DEFAULT 0,
                    avg_render_time REAL,
                    total_render_time REAL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
            """)

            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks(job_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_worker ON tasks(assigned_worker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_online ON workers(is_online)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_stats_worker ON worker_stats(worker_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_stats_timestamp ON worker_stats(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_stats_job ON job_stats(job_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_stats_timestamp ON job_stats(timestamp)")

            conn.commit()

    # ========== Job Methods ==========

    def save_job(self, job_data: Dict[str, Any]) -> None:
        """
        Save or update a job.

        Args:
            job_data: Job data dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            metadata_json = json.dumps(job_data.get("metadata", {})) if job_data.get("metadata") else None

            cursor.execute("""
                INSERT OR REPLACE INTO jobs (
                    id, name, blend_file_path, packed_file_path, blend_file_hash,
                    frame_start, frame_end, status, priority, created_at,
                    started_at, completed_at, blender_version, metadata, output_dir
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data["id"],
                job_data.get("name", ""),
                str(job_data.get("blend_file_path", "")) if job_data.get("blend_file_path") else None,
                str(job_data.get("packed_file_path", "")) if job_data.get("packed_file_path") else None,
                job_data.get("blend_file_hash"),
                job_data.get("frame_start", 0),
                job_data.get("frame_end", 0),
                job_data.get("status", JobStatus.PENDING),
                job_data.get("priority", 0),
                job_data.get("created_at", datetime.now()),
                job_data.get("started_at"),
                job_data.get("completed_at"),
                job_data.get("blender_version"),
                metadata_json,
                str(job_data.get("output_dir", "")) if job_data.get("output_dir") else None,
            ))

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a job by ID.

        Args:
            job_id: Job ID

        Returns:
            Job data dictionary or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()

            if not row:
                return None

            job = dict(row)
            if job.get("metadata"):
                job["metadata"] = json.loads(job["metadata"])
            return job

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List jobs with optional filtering.

        Args:
            status: Optional status filter
            limit: Optional limit on results
            offset: Offset for pagination

        Returns:
            List of job dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM jobs WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC"

            if limit:
                query += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            jobs = []
            for row in rows:
                job = dict(row)
                if job.get("metadata"):
                    job["metadata"] = json.loads(job["metadata"])
                jobs.append(job)

            return jobs

    def update_job_status(self, job_id: str, status: JobStatus, **kwargs) -> None:
        """
        Update job status and optional fields.

        Args:
            job_id: Job ID
            status: New status
            **kwargs: Additional fields to update (started_at, completed_at, etc.)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            updates = ["status = ?"]
            params = [status]

            if "started_at" in kwargs:
                updates.append("started_at = ?")
                params.append(kwargs["started_at"])

            if "completed_at" in kwargs:
                updates.append("completed_at = ?")
                params.append(kwargs["completed_at"])

            if "metadata" in kwargs:
                updates.append("metadata = ?")
                params.append(json.dumps(kwargs["metadata"]))

            params.append(job_id)

            cursor.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                params
            )

    def delete_job(self, job_id: str) -> None:
        """
        Delete a job and all associated tasks.

        Args:
            job_id: Job ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # ========== Task Methods ==========

    def save_task(self, task_data: Dict[str, Any]) -> None:
        """
        Save or update a task.

        Args:
            task_data: Task data dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO tasks (
                    id, job_id, frame_number, status, assigned_worker,
                    assigned_at, started_at, completed_at, render_time_seconds,
                    output_file_path, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_data["id"],
                task_data["job_id"],
                task_data["frame_number"],
                task_data.get("status", TaskStatus.PENDING),
                task_data.get("assigned_worker"),
                task_data.get("assigned_at"),
                task_data.get("started_at"),
                task_data.get("completed_at"),
                task_data.get("render_time_seconds"),
                str(task_data.get("output_file_path", "")) if task_data.get("output_file_path") else None,
                task_data.get("error_message"),
            ))

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task data dictionary or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return dict(row)

    def get_job_tasks(
        self,
        job_id: str,
        status: Optional[TaskStatus] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all tasks for a job.

        Args:
            job_id: Job ID
            status: Optional status filter

        Returns:
            List of task dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM tasks WHERE job_id = ?"
            params = [job_id]

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY frame_number"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    def update_task_status(self, task_id: str, status: TaskStatus, **kwargs) -> None:
        """
        Update task status and optional fields.

        Args:
            task_id: Task ID
            status: New status
            **kwargs: Additional fields to update
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            updates = ["status = ?"]
            params = [status]

            if "assigned_worker" in kwargs:
                updates.append("assigned_worker = ?")
                params.append(kwargs["assigned_worker"])

            if "assigned_at" in kwargs:
                updates.append("assigned_at = ?")
                params.append(kwargs["assigned_at"])

            if "started_at" in kwargs:
                updates.append("started_at = ?")
                params.append(kwargs["started_at"])

            if "completed_at" in kwargs:
                updates.append("completed_at = ?")
                params.append(kwargs["completed_at"])

            if "render_time_seconds" in kwargs:
                updates.append("render_time_seconds = ?")
                params.append(kwargs["render_time_seconds"])

            if "output_file_path" in kwargs:
                updates.append("output_file_path = ?")
                params.append(str(kwargs["output_file_path"]) if kwargs["output_file_path"] else None)

            if "error_message" in kwargs:
                updates.append("error_message = ?")
                params.append(kwargs["error_message"])

            params.append(task_id)

            cursor.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                params
            )

    # ========== Worker Methods ==========

    def save_worker(self, worker_data: Dict[str, Any]) -> None:
        """
        Save or update a worker.

        Args:
            worker_data: Worker data dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            metadata_json = json.dumps(worker_data.get("metadata", {})) if worker_data.get("metadata") else None

            cursor.execute("""
                INSERT OR REPLACE INTO workers (
                    id, name, hostname, address, port, cpu_cores, cpu_threads,
                    ram_gb, gpu_name, gpu_vram_gb, blender_version,
                    last_seen, is_online, current_task_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                worker_data["id"],
                worker_data.get("name", ""),
                worker_data.get("hostname"),
                worker_data.get("address"),
                worker_data.get("port"),
                worker_data.get("cpu_cores"),
                worker_data.get("cpu_threads"),
                worker_data.get("ram_gb"),
                worker_data.get("gpu_name"),
                worker_data.get("gpu_vram_gb"),
                worker_data.get("blender_version"),
                worker_data.get("last_seen", datetime.now()),
                worker_data.get("is_online", False),
                worker_data.get("current_task_id"),
                metadata_json,
            ))

    def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a worker by ID.

        Args:
            worker_id: Worker ID

        Returns:
            Worker data dictionary or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workers WHERE id = ?", (worker_id,))
            row = cursor.fetchone()

            if not row:
                return None

            worker = dict(row)
            if worker.get("metadata"):
                worker["metadata"] = json.loads(worker["metadata"])
            return worker

    def list_workers(self, online_only: bool = False) -> List[Dict[str, Any]]:
        """
        List all workers.

        Args:
            online_only: Only return online workers

        Returns:
            List of worker dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM workers"
            params = []

            if online_only:
                query += " WHERE is_online = 1"

            query += " ORDER BY last_seen DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            workers = []
            for row in rows:
                worker = dict(row)
                if worker.get("metadata"):
                    worker["metadata"] = json.loads(worker["metadata"])
                workers.append(worker)

            return workers

    def update_worker_online_status(self, worker_id: str, is_online: bool) -> None:
        """
        Update worker online status.

        Args:
            worker_id: Worker ID
            is_online: Online status
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE workers SET is_online = ?, last_seen = ? WHERE id = ?",
                (is_online, datetime.now(), worker_id)
            )

    # ========== Statistics Methods ==========

    def save_worker_stats(self, worker_id: str, stats: Dict[str, Any]) -> None:
        """
        Save worker statistics snapshot.

        Args:
            worker_id: Worker ID
            stats: Statistics dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO worker_stats (
                    worker_id, timestamp, cpu_usage, ram_usage, gpu_usage,
                    tasks_completed, tasks_failed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                worker_id,
                stats.get("timestamp", datetime.now()),
                stats.get("cpu_usage"),
                stats.get("ram_usage"),
                stats.get("gpu_usage"),
                stats.get("tasks_completed", 0),
                stats.get("tasks_failed", 0),
            ))

    def save_job_stats(self, job_id: str, stats: Dict[str, Any]) -> None:
        """
        Save job statistics snapshot.

        Args:
            job_id: Job ID
            stats: Statistics dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO job_stats (
                    job_id, timestamp, frames_completed, frames_total,
                    frames_failed, avg_render_time, total_render_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                stats.get("timestamp", datetime.now()),
                stats.get("frames_completed", 0),
                stats.get("frames_total", 0),
                stats.get("frames_failed", 0),
                stats.get("avg_render_time"),
                stats.get("total_render_time"),
            ))

    def get_job_statistics(self, job_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get job statistics history.

        Args:
            job_id: Job ID
            limit: Maximum number of records to return

        Returns:
            List of statistics dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM job_stats
                WHERE job_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (job_id, limit))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_worker_statistics(self, worker_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get worker statistics history.

        Args:
            worker_id: Worker ID
            limit: Maximum number of records to return

        Returns:
            List of statistics dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM worker_stats
                WHERE worker_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (worker_id, limit))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]
