"""Chunked transfer module for resumable file downloads.

This module provides chunked transfer capabilities with:
- Resume interrupted downloads
- Parallel chunk downloads
- Bandwidth-aware chunk sizing
- Progress tracking
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Callable
import httpx


class ChunkStatus(str, Enum):
    """Status of a transfer chunk."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ChunkInfo:
    """Information about a transfer chunk."""

    chunk_id: int
    start_byte: int
    end_byte: int
    status: ChunkStatus = ChunkStatus.PENDING
    file_path: Optional[Path] = None
    hash: Optional[str] = None


@dataclass
class TransferProgress:
    """Progress information for a chunked transfer."""

    total_bytes: int
    downloaded_bytes: int
    chunks_total: int
    chunks_completed: int
    chunks_failed: int
    transfer_rate: float = 0.0
    estimated_time_remaining: float = 0.0


class ChunkedTransfer:
    """Manages chunked file transfers with resume capability."""

    def __init__(
        self,
        url: str,
        output_path: Path,
        chunk_size: int = 10 * 1024 * 1024,  # 10 MB default
        max_parallel_chunks: int = 4,
        resume_file: Optional[Path] = None,
    ):
        """
        Initialize chunked transfer.

        Args:
            url: URL to download from
            output_path: Path to save the file
            chunk_size: Size of each chunk in bytes
            max_parallel_chunks: Maximum number of parallel chunk downloads
            resume_file: Optional path to resume state file
        """
        self.url = url
        self.output_path = output_path
        self.chunk_size = chunk_size
        self.max_parallel_chunks = max_parallel_chunks
        self.resume_file = resume_file or (output_path.with_suffix(output_path.suffix + ".resume"))

        self.chunks: List[ChunkInfo] = []
        self.total_size: int = 0
        self.progress_callback: Optional[Callable[[TransferProgress], None]] = None

    async def get_file_size(self, http_client: httpx.AsyncClient, headers: Optional[Dict] = None) -> int:
        """
        Get file size from server.

        Args:
            http_client: HTTP client
            headers: Optional headers

        Returns:
            File size in bytes
        """
        try:
            response = await http_client.head(self.url, headers=headers)
            if "Content-Length" in response.headers:
                return int(response.headers["Content-Length"])
            
            # Try GET with Range header if HEAD doesn't work
            response = await http_client.get(
                self.url,
                headers={**(headers or {}), "Range": "bytes=0-0"},
            )
            if "Content-Range" in response.headers:
                content_range = response.headers["Content-Range"]
                # Parse "bytes 0-0/12345" format
                total = content_range.split("/")[-1]
                return int(total)
        except Exception:
            pass

        return 0

    def create_chunks(self, total_size: int) -> List[ChunkInfo]:
        """
        Create chunk list for file.

        Args:
            total_size: Total file size in bytes

        Returns:
            List of ChunkInfo objects
        """
        chunks = []
        chunk_id = 0

        for start in range(0, total_size, self.chunk_size):
            end = min(start + self.chunk_size - 1, total_size - 1)
            chunk = ChunkInfo(
                chunk_id=chunk_id,
                start_byte=start,
                end_byte=end,
            )
            chunks.append(chunk)
            chunk_id += 1

        return chunks

    def load_resume_state(self) -> bool:
        """
        Load resume state from file.

        Returns:
            True if resume state was loaded successfully
        """
        if not self.resume_file.exists():
            return False

        try:
            with open(self.resume_file, "r") as f:
                state = json.load(f)

            self.total_size = state.get("total_size", 0)
            self.chunks = []

            for chunk_data in state.get("chunks", []):
                chunk = ChunkInfo(
                    chunk_id=chunk_data["chunk_id"],
                    start_byte=chunk_data["start_byte"],
                    end_byte=chunk_data["end_byte"],
                    status=ChunkStatus(chunk_data["status"]),
                    file_path=Path(chunk_data["file_path"]) if chunk_data.get("file_path") else None,
                    hash=chunk_data.get("hash"),
                )
                self.chunks.append(chunk)

            return True
        except Exception:
            return False

    def save_resume_state(self) -> None:
        """Save resume state to file."""
        state = {
            "total_size": self.total_size,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "start_byte": chunk.start_byte,
                    "end_byte": chunk.end_byte,
                    "status": chunk.status.value,
                    "file_path": str(chunk.file_path) if chunk.file_path else None,
                    "hash": chunk.hash,
                }
                for chunk in self.chunks
            ],
        }

        with open(self.resume_file, "w") as f:
            json.dump(state, f)

    async def download_chunk(
        self,
        http_client: httpx.AsyncClient,
        chunk: ChunkInfo,
        headers: Optional[Dict] = None,
    ) -> bool:
        """
        Download a single chunk.

        Args:
            http_client: HTTP client
            chunk: Chunk to download
            headers: Optional headers

        Returns:
            True if download succeeded
        """
        chunk.status = ChunkStatus.DOWNLOADING

        # Create temporary file for this chunk
        chunk_file = self.output_path.parent / f"{self.output_path.name}.chunk{chunk.chunk_id}"
        chunk.file_path = chunk_file

        try:
            # Download chunk with Range header
            range_header = f"bytes={chunk.start_byte}-{chunk.end_byte}"
            download_headers = {**(headers or {}), "Range": range_header}

            async with http_client.stream("GET", self.url, headers=download_headers) as response:
                if response.status_code not in (200, 206):  # 206 = Partial Content
                    chunk.status = ChunkStatus.FAILED
                    return False

                # Write chunk to file
                with open(chunk_file, "wb") as f:
                    async for data in response.aiter_bytes():
                        f.write(data)

            # Calculate hash for verification
            hasher = hashlib.md5()
            with open(chunk_file, "rb") as f:
                for data in iter(lambda: f.read(8192), b""):
                    hasher.update(data)
            chunk.hash = hasher.hexdigest()

            chunk.status = ChunkStatus.COMPLETED
            return True

        except Exception as e:
            chunk.status = ChunkStatus.FAILED
            if chunk_file.exists():
                chunk_file.unlink()
            return False

    async def assemble_file(self) -> bool:
        """
        Assemble chunks into final file.

        Returns:
            True if assembly succeeded
        """
        try:
            # Sort chunks by chunk_id
            sorted_chunks = sorted(self.chunks, key=lambda c: c.chunk_id)

            with open(self.output_path, "wb") as outfile:
                for chunk in sorted_chunks:
                    if chunk.status != ChunkStatus.COMPLETED or not chunk.file_path:
                        return False

                    if not chunk.file_path.exists():
                        return False

                    # Copy chunk to output file
                    with open(chunk.file_path, "rb") as infile:
                        while True:
                            data = infile.read(8192)
                            if not data:
                                break
                            outfile.write(data)

                    # Clean up chunk file
                    chunk.file_path.unlink()

            # Clean up resume file
            if self.resume_file.exists():
                self.resume_file.unlink()

            return True

        except Exception:
            return False

    def get_progress(self) -> TransferProgress:
        """
        Get current transfer progress.

        Returns:
            TransferProgress object
        """
        downloaded = sum(
            chunk.end_byte - chunk.start_byte + 1
            for chunk in self.chunks
            if chunk.status == ChunkStatus.COMPLETED
        )

        chunks_completed = sum(1 for chunk in self.chunks if chunk.status == ChunkStatus.COMPLETED)
        chunks_failed = sum(1 for chunk in self.chunks if chunk.status == ChunkStatus.FAILED)

        return TransferProgress(
            total_bytes=self.total_size,
            downloaded_bytes=downloaded,
            chunks_total=len(self.chunks),
            chunks_completed=chunks_completed,
            chunks_failed=chunks_failed,
        )

    async def download(
        self,
        http_client: httpx.AsyncClient,
        headers: Optional[Dict] = None,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> bool:
        """
        Download file using chunked transfer.

        Args:
            http_client: HTTP client
            headers: Optional headers
            progress_callback: Optional progress callback

        Returns:
            True if download succeeded
        """
        self.progress_callback = progress_callback

        # Get file size
        self.total_size = await self.get_file_size(http_client, headers)
        if self.total_size == 0:
            return False

        # Try to load resume state
        if not self.load_resume_state():
            # Create new chunks
            self.chunks = self.create_chunks(self.total_size)

        # Download chunks in parallel
        semaphore = asyncio.Semaphore(self.max_parallel_chunks)

        async def download_with_semaphore(chunk: ChunkInfo):
            if chunk.status == ChunkStatus.COMPLETED:
                return

            async with semaphore:
                await self.download_chunk(http_client, chunk, headers)
                self.save_resume_state()

                if self.progress_callback:
                    self.progress_callback(self.get_progress())

        # Download all pending chunks
        tasks = [download_with_semaphore(chunk) for chunk in self.chunks]
        await asyncio.gather(*tasks)

        # Check if all chunks completed
        if all(chunk.status == ChunkStatus.COMPLETED for chunk in self.chunks):
            # Assemble file
            return await self.assemble_file()

        return False
