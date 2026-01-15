# User Guide

## Installation

WeRender is a Python package that orchestrates Blender for you.

### Prerequisites

1. **Python 3.10+** installed.
2. **Blender 4.0+** installed and added to your system PATH (the `blender` command must work in your terminal).
3. All computers must be on the **same local network**.

### Install via Pip

Run this on **every computer** you want to use (both the main one and the render nodes):

```bash
pip install werender
```

---

## Usage

### 1. Start the Coordinator (Your Main PC)

This is the computer where you have your Blender file.

```bash
# Basic usage
werender coordinator --file my_project.blend --frames 1-250

# Just start the server (you can upload files later via the dashboard)
werender coordinator
```

The Coordinator will start a web dashboard at `http://localhost:8420`.

### 2. Start Workers (Other Computers)

On your other laptops or desktops, simply run:

```bash
werender worker
```

That's it! The worker will:

1. Automatically look for the Coordinator on the network.
2. Connect and register itself.
3. Start downloading and rendering frames when a job is available.

---

## Web Dashboard

Open `http://localhost:8420` on your Coordinator machine (or use its local IP, e.g., `http://192.168.1.5:8420`, to view from your phone).

### Features

- **Overview**: See active workers, CPU/RAM usage, and overall progress.
- **Jobs**: Upload new `.blend` files or restart previous jobs.
- **Workers**: View detailed stats of every connected node.
- **Results**: Preview rendered frames as they come in.

---

## Troubleshooting

### Q: Workers can't find the Coordinator

- **Firewall**: Ensure your firewall allows Python to accept incoming connections on port **8420** (TCP) and **5353** (UDP for mDNS).
- **Network Profile**: On Windows, ensure your network is set to "Private" rather than "Public". Public networks often block discovery protocols.

### Q: Blender not found

- Ensure you can type `blender --version` in your terminal. If not, add the folder containing `blender.exe` to your system's Environment Variables (Path).
