# WeRender

**Zero-Config Peer-to-Peer Distributed Render Manager for Blender**

Turn any collection of computers on your network into a render farm. No server setup, no IP configuration—just open the app and start rendering.

## Features

- 🔍 **Zero Configuration** - Automatic discovery via mDNS (Zeroconf)
- 🎬 **Blender Native** - Built for Cycles and Eevee
- 📦 **Pack & Go** - Automatic asset packing, no missing textures
- 💪 **Fault Tolerant** - Auto-recovery when workers disconnect
- 📊 **Real-time Dashboard** - Monitor from any device on your network
- 🌐 **Web Interface** - Control jobs and workers from your browser

## Quick Start

### Installation

```bash
pip install werender
```

### As Coordinator (Main PC)

```bash
werender coordinator --file myproject.blend --frames 1-100
```

Then open your browser to `http://localhost:8420` to view the dashboard!

### As Worker (Other Machines)

```bash
werender worker
```

Workers automatically discover the coordinator and start rendering!

## Dashboard Features

The web dashboard (available at `http://localhost:8420`) provides:

- **Real-time Monitoring**: Watch jobs progress and worker status in real-time
- **Job Management**: Create, start, pause, resume, and cancel render jobs
- **Worker Grid**: View all connected workers with their specs and current tasks
- **Stats Overview**: See total frames, completed frames, running jobs, and active workers
- **Remote Access**: Monitor and control your render farm from any device on your network

## Requirements

- Python 3.10+
- Blender 4.0+ (must be installed and accessible)
- All machines on the same local network

## Development

```bash
# Clone the repository
git clone https://github.com/yourusername/werender.git
cd werender

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest
```

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   Coordinator   │◄───────►│    Worker A     │
│  (Your Main PC) │         │  (Old Laptop)   │
│                 │         └─────────────────┘
│  • Job Queue    │
│  • File Server  │         ┌─────────────────┐
│  • WebSocket    │◄───────►│    Worker B     │
│  • Dashboard    │         │  (Desktop)      │
└─────────────────┘         └─────────────────┘
        │
        ▼
   ┌─────────┐
   │ Browser │  (Monitor from phone/tablet)
   └─────────┘
```

## Commands

### Coordinator Mode
```bash
werender coordinator [OPTIONS]
```

Options:
- `--file PATH` - Path to .blend file (optional, can upload via dashboard)
- `--frames START-END` - Frame range (e.g., 1-100)
- `--port PORT` - Port to run server on (default: 8420)

### Worker Mode
```bash
werender worker [OPTIONS]
```

Options:
- `--port PORT` - Coordinator port (default: 8420)
- `--max-concurrent N` - Maximum concurrent tasks (default: 1)

### Info
```bash
werender info
```
Display system information and Blender version.

## License

MIT