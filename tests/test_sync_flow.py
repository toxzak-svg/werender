
import asyncio
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path
import uvicorn
import httpx

from werender.network.coordinator import CoordinatorServer
from werender.network.worker import WorkerNode

def create_dummy_addon(addons_dir: Path, name: str):
    """Create a dummy add-on zip file."""
    addons_dir.mkdir(parents=True, exist_ok=True)
    zip_path = addons_dir / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{name}/__init__.py", "print('Hello Addon')")
    return zip_path

def run_coordinator(coordinator):
    """Run coordinator (blocking)."""
    try:
        from uvicorn import Config, Server
        config = Config(coordinator.app, host="127.0.0.1", port=8425, log_level="error")
        server = Server(config)
        # We need to run this in a thread, but uvicorn expects to manage the loop.
        # So we just run it blocking here, and the thread handles it.
        server.run()
    except Exception as e:
        print(f"Coordinator error: {e}")

async def run_test():
    # Setup directories
    temp_dir = Path(tempfile.mkdtemp())
    coord_config_dir = temp_dir / "coordinator_config"
    worker_config_dir = temp_dir / "worker_config"
    
    # Mock home for coordinator and worker to separate their storages
    # We can't easily mock Path.home() globally, but we can patch the instances
    # Or just rely on the fact that we can set properties on the instances if we modified the classes to accept them.
    # But `coordinator.py` hardcodes `Path.home() / ".werender"`.
    # To test this properly without messing with user's home, I should allow overriding config_dir in __init__.
    # For now, I will monkeypatch in the test.
    
    print("🔧 Setting up test environment...")
    
    # Create dummy add-on for Coordinator
    addons_source = coord_config_dir / "addons"
    create_dummy_addon(addons_source, "test_addon_v1")
    
    # Initialize Coordinator
    coordinator = CoordinatorServer(port=8425)
    # Patch config paths
    coordinator.config_dir = coord_config_dir
    coordinator.sync_manager.config_path = coord_config_dir / "werender.json"
    coordinator.sync_manager.addons_dir = addons_source
    
    # Create global settings file
    (coord_config_dir / "werender.json").write_text('{"render_timeout": 300}')

    # Start Coordinator in a separate thread
    print("🚀 Starting Coordinator...")
    coord_thread = threading.Thread(target=run_coordinator, args=(coordinator,), daemon=True)
    coord_thread.start()
    
    # Wait for startup
    await asyncio.sleep(2)
    
    # Initialize Worker
    print("👷 Starting Worker...")
    worker = WorkerNode(name="TestSyncWorker", port=8426)
    # Patch worker paths
    worker.config_dir = worker_config_dir
    worker.addons_dir = worker_config_dir / "addons"
    worker.addons_dir.mkdir(parents=True, exist_ok=True)
    
    # Start worker flow (non-blocking validation)
    worker.http_client = httpx.AsyncClient(timeout=5.0)
    
    # Manually trigger discovery callback to skip zeroconf in test execution env
    from werender.network.discovery import NodeInfo
    worker._on_coordinator_discovered(NodeInfo(
        name=f"WeRender-coordinator-{coordinator.node_id}._werender.tcp.local.",
        address="127.0.0.1",
        port=8425,
        node_type="coordinator",
        properties={
            "node_id": coordinator.node_id,
            "hostname": "localhost",
            "blender_version": "4.0.0" 
        }
    ))
    
    # Trigger Sync
    await worker._sync_with_coordinator()
    
    # Validation
    print("\n🔍 Verifying results...")
    
    # 1. Check Settings
    if worker.settings.get("render_timeout") == 300:
        print("✅ Settings synced successfully")
    else:
        print(f"❌ Settings sync failed. Got: {worker.settings}")
        
    # 2. Check Add-ons
    expected_zip = worker.addons_dir / "test_addon_v1.zip"
    if expected_zip.exists():
        print("✅ Add-on zip downloaded")
    else:
        print("❌ Add-on zip missing")
        
    # 3. Check Add-on Manifest/Extraction
    # In our mock implementation, we extract to `addons_dir`.
    extracted_file = worker.addons_dir / "test_addon_v1" / "__init__.py"
    if extracted_file.exists():
        print("✅ Add-on extracted successfully")
    else:
        print(f"❌ Add-on extraction failed. Listing dir: {list(worker.addons_dir.rglob('*'))}")

    # Cleanup
    worker.stop()
    # Coordinator thread will die with main process
    shutil.rmtree(temp_dir)

if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        pass
