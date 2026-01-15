# Development Guide

## Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/yourusername/werender.git
   cd werender
   ```

2. **Create a Virtual Environment**

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install in Editable Mode**
   This installs the package with all development dependencies (pytest, ruff, etc.).

   ```bash
   pip install -e ".[dev]"
   ```

## Project Structure

- `src/werender/`
  - `core/`: Core logic for Job, Node (Worker/Coordinator), and Configuration management.
  - `network/`: WebSocket and HTTP server/client implementations + mDNS discovery.
  - `dashboard/`: React/Static files for the web interface.
  - `addons/`: The Blender add-on script (`werender_submitter.py`) used inside Blender.
  - `scheduler/`: Logic for assigning frames to workers.

## Running Tests

We use `pytest` for testing.

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_discovery.py
```

## Code Style

We use `ruff` for linting and formatting.

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .
```

## Building

To build the package for distribution:

```bash
pip install build
python -m build
```

This will create a `.whl` and `.tar.gz` in the `dist/` directory.
