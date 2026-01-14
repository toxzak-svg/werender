# multirender

**Zero-Config Peer-to-Peer Distributed Render Manager for Blender**

Turn any collection of computers on your network into a render farm. No server setup, no IP configuration—just open the app and start rendering.

## Features

- 🔍 **Zero Configuration** - Automatic discovery via mDNS (Zeroconf)
- 🎬 **Blender Native** - Built for Cycles and Eevee
- 📦 **Pack & Go** - Automatic asset packing, no missing textures
- 💪 **Fault Tolerant** - Auto-recovery when workers disconnect
- 📊 **Real-time Dashboard** - Monitor from any device on your network

## Quick Start

### Installation

```bash
pip install multirender
```

### As Coordinator (Main PC)

```bash
multirender coordinator --file myproject.blend --frames 1-100
```

### As Worker (Other Machines)

```bash
multirender worker
```

Workers automatically discover the coordinator and start rendering!

## Requirements

- Python 3.10+
- Blender 4.0+ (must be installed and accessible)
- All machines on the same local network

## Development

```bash
# Clone the repository
git clone https://github.com/yourusername/multirender.git
cd multirender

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

## License

MIT
