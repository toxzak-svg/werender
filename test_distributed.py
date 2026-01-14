"""Test script for distributed rendering functionality.

This script demonstrates how to use the WeRender distributed rendering system.
Run this in two separate terminals:

Terminal 1 (Coordinator):
    python test_distributed.py coordinator

Terminal 2 (Worker):
    python test_distributed.py worker
"""

import argparse
import sys
from pathlib import Path

from werender.network.coordinator import CoordinatorServer
from werender.network.worker import WorkerNode


def test_coordinator():
    """Test coordinator mode."""
    print("=" * 60)
    print("Starting Coordinator Server...")
    print("=" * 60)
    print()
    print("The coordinator will:")
    print("  1. Advertise itself via mDNS (Zeroconf)")
    print("  2. Wait for workers to connect")
    print("  3. Accept HTTP API requests for job management")
    print()
    print("API Endpoints:")
    print("  POST   /api/jobs/create      - Create a new render job")
    print("  GET    /api/jobs              - List all jobs")
    print("  GET    /api/jobs/{id}         - Get job details")
    print("  POST   /api/jobs/{id}/start   - Start rendering")
    print("  GET    /api/workers           - List connected workers")
    print()
    print("Example: Create a job with curl:")
    print('  curl -X POST http://localhost:8420/api/jobs/create \\')
    print('    -F "file=@/path/to/project.blend" \\')
    print('    -F "frame_start=1" \\')
    print('    -F "frame_end=10" \\')
    print('    -F "name=Test Job"')
    print()
    print("=" * 60)
    print()

    coordinator = CoordinatorServer(port=8420)
    coordinator.run()


def test_worker():
    """Test worker mode."""
    print("=" * 60)
    print("Starting Worker Node...")
    print("=" * 60)
    print()
    print("The worker will:")
    print("  1. Advertise itself via mDNS (Zeroconf)")
    print("  2. Discover coordinators on the network")
    print("  3. Request tasks and render frames")
    print()
    print("=" * 60)
    print()

    worker = WorkerNode(name="TestWorker")
    worker.start()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test WeRender distributed rendering"
    )
    subparsers = parser.add_subparsers(dest="mode", help="Mode to run")

    coordinator_parser = subparsers.add_parser(
        "coordinator",
        help="Run as coordinator"
    )
    coordinator_parser.set_defaults(func=test_coordinator)

    worker_parser = subparsers.add_parser(
        "worker",
        help="Run as worker"
    )
    worker_parser.set_defaults(func=test_worker)

    args = parser.parse_args()

    if not args.mode:
        parser.print_help()
        return 1

    args.func()
    return 0


if __name__ == "__main__":
    sys.exit(main())