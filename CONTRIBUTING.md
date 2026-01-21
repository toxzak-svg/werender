# Contributing to WeRender

Thank you for your interest in contributing to WeRender! This document provides guidelines for contributing to the project.

## Code of Conduct

Please be respectful and constructive in all interactions. We're building a welcoming community for animators and developers alike.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally
3. **Set up the development environment** - See [Development Guide](docs/development.md)

## How to Contribute

### Reporting Bugs

- Check existing issues to avoid duplicates
- Use the bug report template
- Include: Python version, OS, Blender version, steps to reproduce

### Suggesting Features

- Open an issue with the `enhancement` label
- Describe the use case and expected behavior
- Explain how it fits the "zero-config" philosophy

### Submitting Pull Requests

1. Create a feature branch from `main`
2. Write tests for new functionality
3. Run the test suite: `pytest`
4. Run linting: `ruff check .`
5. Submit a PR with a clear description

## Development Workflow

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest

# Check code style
ruff check .

# Auto-fix issues
ruff check --fix .
```

## Pull Request Guidelines

- Keep PRs focused on a single change
- Update documentation if needed
- Ensure all tests pass
- Follow existing code style

## Questions?

Open an issue or reach out to the maintainers. We're happy to help!
