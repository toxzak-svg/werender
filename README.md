# WeRender

**Zero-Config Peer-to-Peer Distributed Render Manager for Blender**

Turn any collection of networked computers into a render farm instantly.

[Architecture](docs/architecture.md) | [User Guide](docs/user_guide.md) | [Development](docs/development.md) | [Security Guide](docs/security/SECURITY_GUIDE.md)

---

## What is WeRender?

WeRender is a lightweight tool that distributes Blender rendering tasks across multiple computers on your local network. It is designed to be **Zero-Config**:

1. **Open WeRender** on your main PC (Coordinator).
2. **Open WeRender** on any other PC (Worker).
3. **Start Rendering**. The workers automatically find the coordinator, download the project, and start helping.

## Why WeRender?

WeRender is designed for situations where traditional render managers are overkill or too complex:

- **No Shared Storage Required**: Unlike Blender's built-in network rendering, WeRender doesn't require a NAS, shared file system, or centralized storage. Blend files and assets are automatically distributed to workers.
- **Zero Manual Configuration**: No IP addresses to configure, no DNS entries to set up, no network mounts to create. WeRender uses mDNS for automatic discovery - just run it and it works.
- **Works on Mixed Hardware**: Combine your powerful desktop, gaming laptop, and old office PC into a single render farm. No need for identical hardware or operating systems.
- **Fault-Tolerant by Design**: Workers can join or leave at any time. If a worker crashes, its frames are automatically reassigned to healthy nodes.
- **No Blender Subscription Required**: Unlike cloud render farms, WeRender uses hardware you already own with no per-frame or monthly costs.

### Example Scenarios

**Indie Studio (3-5 PCs)**
- Setup: Artist workstation + 2 render nodes + 1 spare laptop
- Speedup: ~3.5x faster than single machine
- Use case: Rendering portfolio pieces or client deliverables over weekends

**Classroom Lab (10-20 PCs)**
- Setup: Instructor station running coordinator, all student machines as workers
- Speedup: ~15x faster for class projects
- Use case: Teaching animation courses, allowing students to see results in class time

**Small VFX Shop (6-10 Workstations)**
- Setup: 3 high-end render nodes + 4 artist workstations (workers when idle)
- Speedup: ~7-8x faster for production renders
- Use case: Tight deadlines on commercial work, overnight batch rendering

**Freelancer on Location**
- Setup: Main laptop + client's spare desktop
- Speedup: ~2x faster renders
- Use case: On-site work where every minute counts

## Features

- 🔍 **Zero Configuration** - Automatic discovery via mDNS (Zeroconf).
- 🔐 **Secure Authentication** - API key-based security to protect your render jobs (see [Security Guide](docs/security/SECURITY_GUIDE.md))
- 🎬 **Blender Native** - Works with standard `.blend` files (Cycles & Eevee).
- 📦 **Automatic Asset Packing** - No missing textures; files are packed and sent to workers automatically.
- 💪 **Fault Tolerant** - If a worker crashes or disconnects, its frames are reassigned automatically. Workers reconnect if they lose network connectivity.
- 🔄 **Worker Recovery** - Workers automatically resync and resume work after network interruptions or coordinator restarts.
- 📊 **Web Dashboard** - Real-time monitoring from any browser on the network.

### Fault Tolerance Details

WeRender handles failures gracefully:

- **Worker Disconnect**: If a worker stops responding (no heartbeat), its assigned frames are returned to the pool and redistributed to healthy workers.
- **Network Interruption**: Workers maintain state and automatically reconnect to the coordinator when connectivity is restored.
- **Coordinator Recovery**: If the coordinator restarts, workers detect the restart and re-establish connections, resuming their work.
- **Frame Reassignment**: Failed frames are automatically redistributed with exponential backoff to prevent cascading failures.

## Project Status

**Current Version**: v0.2.0-beta (Beta Release)

**Maturity**: Beta - Core functionality is stable and production-ready for many use cases. Active development continues on performance optimizations and UI improvements.

**Known Limitations**:
- **OS Support**: Primarily tested on Windows, macOS, and Linux (Ubuntu/Debian). Other Linux distributions may work but are less tested.
- **Blender Versions**: Tested with Blender 4.0+. Blender 3.6 and earlier may have compatibility issues.
- **Animation vs Stills**: Fully supports both. Complex compositing nodes may require additional testing.
- **Large Projects**: Projects >10GB may experience slower initial sync times (optimization planned for v0.3.0).

**Upcoming Features** (Roadmap):
- Enhanced dashboard UI with per-frame progress visualization
- Performance metrics and benchmarking tools
- Cloud worker support (AWS, GCP, Azure)
- Priority queuing for multiple concurrent jobs
- GPU/CPU selection per worker
- Mobile app for monitoring

## Quick Start

### Step 1: Installation

WeRender requires Python 3.10+ and Blender 4.0+ (in your system PATH).

```bash
pip install werender
```

### Step 2: Start the Coordinator

On your main computer (where your Blender file is):

```bash
werender coordinator --file myproject.blend --frames 1-100
```

**Expected Output:**
```
✓ Starting WeRender Coordinator...
✓ API keys generated: ~/.werender/api_keys.json
✓ Worker API Key: wrk_xxxxxxxxxxxxxxxx
✓ Coordinator API Key: coord_xxxxxxxxxxxxxxxx
✓ mDNS service registered: werender-coordinator.local
✓ Web dashboard: http://localhost:8420
✓ Coordinator ready and listening for workers...
```

The coordinator will print a **Worker API Key** - copy this for the next step.

### Step 3: Start Workers

On each worker computer, you can either:

**Option A: Using the API key (Recommended)**
```bash
# Set the environment variable
export WERENDER_API_KEY="wrk_xxxxxxxxxxxxxxxx"  # Use the key from Step 2

# Start the worker
werender worker
```

**Option B: Using shared config directory**
```bash
# Copy the api_keys.json from coordinator to worker
# Then simply run:
werender worker
```

**Expected Worker Output:**
```
✓ Starting WeRender Worker...
✓ Searching for coordinator on network...
✓ Found coordinator: coordinator.local (192.168.1.100:8420)
✓ Authenticating with coordinator...
✓ Worker registered successfully: worker-01
✓ Waiting for render tasks...
```

### Step 4: Monitor Progress

Open your browser and navigate to:

```
http://localhost:8420
```

You'll see:
- Connected workers with their CPU/RAM usage
- Job progress (frames completed, remaining, failed)
- Real-time frame previews as they render

### Demo Project

Want to test without using your own files?

```bash
# Download a small demo project
curl -O https://github.com/toxzak-svg/werender/releases/download/v0.2.0/demo-cube.blend

# Start coordinator with the demo
werender coordinator --file demo-cube.blend --frames 1-10
```

This demo renders a simple animated cube in ~10-30 seconds per frame, perfect for testing your setup.

For more detailed instructions and troubleshooting, see the [User Guide](docs/user_guide.md).

## Documentation

- **[User Guide](docs/user_guide.md)** - Installation, usage, and dashboard features
- **[Architecture](docs/architecture.md)** - Hub-and-spoke design and data flow
- **[Security Guide](docs/security/SECURITY_GUIDE.md)** - Authentication setup and best practices
- **[Development](docs/development.md)** - Setup for contributors
- **[API Reference](docs/api/README.md)** - HTTP and WebSocket API documentation
- **[Contributing](CONTRIBUTING.md)** - How to contribute to the project
- **[Changelog](CHANGELOG.md)** - Version history and changes

## Community & Support

### Getting Help

- **GitHub Issues**: For bug reports and feature requests
- **GitHub Discussions**: For questions, setup help, and community discussions
- **Security Issues**: Email security@werender.dev for security vulnerabilities

### Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Priority Areas for Contribution:**
- Testing on different OS/hardware combinations
- Dashboard UI improvements (React/Vue experience helpful)
- Windows support enhancements
- Documentation and tutorials
- Performance benchmarking

**Good First Issues**: Look for issues labeled `good first issue` in the GitHub repository. These are perfect for new contributors and include detailed guidance.

### Share Your Setup

We'd love to feature your render farm setup! Share your:
- Number of machines and their specs
- Typical speedup ratios
- Screenshots of your dashboard
- Use case and workflow

Submit via GitHub Discussions with the "Users & Setups" tag, and we'll add it to our documentation!

## License

MIT

---

**Turn your idle computers into render power. Start rendering faster today.** 🚀