# WeRender

**Zero-Config Peer-to-Peer Distributed Render Manager for Blender**

Turn any collection of networking computers into a render farm instantly.

[Architecture](docs/architecture.md) | [User Guide](docs/user_guide.md) | [Development](docs/development.md)

---

## What is WeRender?

WeRender is a lightweight tool that distributes Blender rendering tasks across multiple computers on your local network. It is designed to be **Zero-Config**:

1. **Open WeRender** on your main PC (Coordinator).
2. **Open WeRender** on any other PC (Worker).
3. **Start Rendering**. The workers automatically find the coordinator, download the project, and start helping.

## Features

- 🔍 **Zero Configuration** - Automatic discovery via mDNS (Zeroconf).
- 🎬 **Blender Native** - Works with standard `.blend` files (Cycles & Eevee).
- 📦 **Automatic Asset Packing** - No missing textures; files are packed and sent to workers automatically.
- 💪 **Fault Tolerant** - If a worker crashes or disconnects, its frames are reassigned.
- 📊 **Web Dashboard** - Real-time monitoring from any browser on the network.

## Quick Start

### Installation

```bash
pip install werender
```

### Usage

**On your Main PC (Coordinator):**

```bash
werender coordinator --file myproject.blend
```

**On other machines (Workers):**

```bash
werender worker
```

For more detailed instructions, see the [User Guide](docs/user_guide.md).

## Documentation

- **[User Guide](docs/user_guide.md)** - Installation, usage, and dashboard features
- **[Architecture](docs/architecture.md)** - Hub-and-spoke design and data flow
- **[Development](docs/development.md)** - Setup for contributors
- **[API Reference](docs/api/README.md)** - HTTP and WebSocket API documentation
- **[Security Guide](docs/security/SECURITY_GUIDE.md)** - Authentication and best practices
- **[Contributing](CONTRIBUTING.md)** - How to contribute to the project
- **[Changelog](CHANGELOG.md)** - Version history

## License

MIT
