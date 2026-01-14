"""WeRender - Distributed Render Manager for Blender.

Main entry point for the CLI application.
"""

import argparse
import sys
from pathlib import Path

from werender.core.blender import BlenderNotFoundError, BlenderRenderer


def cmd_render(args: argparse.Namespace) -> int:
    """Execute local render command."""
    print(f"🎬 WeRender - Local Render Test")
    print(f"=" * 50)

    # Parse frame range
    if "-" in args.frames:
        start, end = map(int, args.frames.split("-"))
    else:
        start = end = int(args.frames)

    blend_file = Path(args.file)
    output_dir = Path(args.output)

    if not blend_file.exists():
        print(f"❌ Error: File not found: {blend_file}")
        return 1

    # Initialize Blender renderer
    try:
        renderer = BlenderRenderer(args.blender or "blender")
        version = renderer.get_version()
        print(f"✓ Found Blender {version}")
    except BlenderNotFoundError as e:
        print(f"❌ {e}")
        return 1

    print(f"📁 Blend file: {blend_file}")
    print(f"📂 Output: {output_dir}")
    print(f"🎞️  Frames: {start}-{end} ({end - start + 1} frames)")
    print()

    # Render frames
    success_count = 0
    fail_count = 0

    for frame in range(start, end + 1):
        print(f"🔄 Rendering frame {frame}...", end=" ", flush=True)
        result = renderer.render_frame(blend_file, frame, output_dir)

        if result.success:
            print(f"✓ Done in {result.render_time:.1f}s → {result.output_file}")
            success_count += 1
        else:
            print(f"✗ Failed: {result.error_message}")
            fail_count += 1

    print()
    print(f"=" * 50)
    print(f"✓ Completed: {success_count} | ✗ Failed: {fail_count}")

    return 0 if fail_count == 0 else 1


def cmd_coordinator(args: argparse.Namespace) -> int:
    """Start the coordinator server."""
    print("🎬 WeRender - Coordinator Mode")
    print("=" * 50)
    print()
    print("⚠️  Coordinator mode is not yet implemented.")
    print("   This will be available in Sprint 3.")
    print()
    print("For now, use 'werender render' to test local rendering.")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Start as a worker node."""
    print("🎬 WeRender - Worker Mode")
    print("=" * 50)
    print()
    print("⚠️  Worker mode is not yet implemented.")
    print("   This will be available in Sprint 2.")
    print()
    print("For now, use 'werender render' to test local rendering.")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Show system information."""
    from werender.utils.system import get_system_specs

    print("🎬 WeRender - System Information")
    print("=" * 50)

    specs = get_system_specs()
    print(f"🖥️  Hostname: {specs.hostname}")
    print(f"🧠 CPU: {specs.cpu_cores} cores / {specs.cpu_threads} threads")
    print(f"💾 RAM: {specs.ram_gb} GB")

    if specs.gpu_name:
        print(f"🎮 GPU: {specs.gpu_name} ({specs.gpu_vram_gb} GB VRAM)")
    else:
        print(f"🎮 GPU: Not detected (NVIDIA GPU required for detection)")

    # Check Blender
    try:
        renderer = BlenderRenderer()
        version = renderer.get_version()
        print(f"🎨 Blender: {version} ✓")
    except BlenderNotFoundError:
        print(f"🎨 Blender: Not found ✗")

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="werender",
        description="Zero-Config Peer-to-Peer Distributed Render Manager for Blender",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # render command
    render_parser = subparsers.add_parser("render", help="Render frames locally (for testing)")
    render_parser.add_argument("-f", "--file", required=True, help="Path to .blend file")
    render_parser.add_argument(
        "--frames", default="1", help="Frame range (e.g., '1-10' or '5')"
    )
    render_parser.add_argument(
        "-o", "--output", default="./output", help="Output directory for rendered frames"
    )
    render_parser.add_argument(
        "--blender", help="Path to Blender executable (optional)"
    )
    render_parser.set_defaults(func=cmd_render)

    # coordinator command
    coord_parser = subparsers.add_parser("coordinator", help="Start as job coordinator")
    coord_parser.add_argument("-f", "--file", help="Path to .blend file to render")
    coord_parser.add_argument("--frames", help="Frame range to render")
    coord_parser.add_argument("-p", "--port", type=int, default=8420, help="API port")
    coord_parser.set_defaults(func=cmd_coordinator)

    # worker command
    worker_parser = subparsers.add_parser("worker", help="Start as render worker")
    worker_parser.add_argument("--name", help="Custom worker name")
    worker_parser.set_defaults(func=cmd_worker)

    # info command
    info_parser = subparsers.add_parser("info", help="Show system information")
    info_parser.set_defaults(func=cmd_info)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
