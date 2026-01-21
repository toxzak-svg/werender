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

## Good First Issues

New contributors are always welcome! Look for issues labeled with `good first issue` in the GitHub repository. These issues are carefully selected to be:

- Well-defined with clear acceptance criteria
- Low complexity and low risk
- Good introduction to the codebase
- Include detailed guidance and code pointers

### Examples of Good First Issues

- Adding more detailed logging to a specific component
- Improving error messages for better user experience
- Writing tests for uncovered code paths
- Updating documentation to clarify usage
- Adding small UI enhancements to the dashboard

If you're unsure where to start, check the `good first issue` label or open a discussion to ask for guidance!

## Priority Contribution Areas

We're actively seeking contributions in these areas:

### Testing & Quality Assurance
- **Impact**: High - Ensures reliability across different environments
- **Skills Needed**: Basic testing, pytest
- **Tasks**:
  - Test on different OS combinations (Windows + macOS, Linux + Windows, etc.)
  - Test with various Blender versions (3.6, 4.0, 4.2)
  - Add integration tests for edge cases (network interruption, worker crash)
  - Performance benchmarking across different hardware

### Dashboard UI Improvements
- **Impact**: Medium - Improves user experience and adoption
- **Skills Needed**: React/Vue, HTML/CSS, JavaScript
- **Tasks**:
  - Add per-frame progress visualization
  - Create mobile-responsive layout
  - Add real-time charts for CPU/RAM usage
  - Improve frame preview gallery
  - Add dark mode support

### Windows Support Enhancements
- **Impact**: High - Many Blender users are on Windows
- **Skills Needed**: Windows system programming, Python
- **Tasks**:
  - Improve mDNS discovery on Windows
  - Better handling of Windows firewall rules
  - Windows service installation support
  - Fix any Windows-specific bugs

### Documentation & Tutorials
- **Impact**: High - Critical for onboarding and adoption
- **Skills Needed**: Technical writing, markdown
- **Tasks**:
  - Create video tutorials for Quick Start
  - Write case studies from real users
  - Add troubleshooting guides for common issues
  - Create example projects for different use cases
  - Translate documentation to other languages

### Performance Optimizations
- **Impact**: Medium - Faster renders = happier users
- **Skills Needed**: Python, performance profiling
- **Tasks**:
  - Optimize large file transfer (>10GB projects)
  - Reduce memory footprint on workers
  - Improve frame distribution algorithm
  - Add support for chunking larger frames

### Accessibility & Internationalization
- **Impact**: Medium - Broader reach
- **Skills Needed**: UX, localization
- **Tasks**:
  - Add keyboard navigation to dashboard
  - Screen reader support
  - Multi-language support for UI
  - High contrast mode

## How to Get Help

If you need help contributing:

1. **GitHub Discussions**: Start a discussion with the `question` or `help wanted` labels
2. **Review PRs**: Look at recently merged pull requests to understand the code style and patterns
3. **Read the Code**: Check out [architecture.md](docs/architecture.md) for system overview
4. **Join Community**: Follow the project on GitHub to stay updated

## Share Your Experience

After contributing, consider sharing your experience:

- Write a short blog post or tutorial about your contribution
- Share your render farm setup in GitHub Discussions (use "Users & Setups" tag)
- Provide feedback on what made contributing easier or harder
- Help other newcomers in discussions

## Questions?

Open an issue or reach out to the maintainers. We're happy to help!