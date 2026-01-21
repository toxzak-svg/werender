# Changelog

All notable changes to WeRender will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project structure
- Coordinator and Worker CLI commands
- mDNS-based zero-config discovery
- WebSocket real-time communication
- Web dashboard for monitoring
- Blender CLI integration for Cycles/Eevee rendering
- Automatic asset packing ("Pack & Go")
- Fault-tolerant frame reassignment
- API key-based authentication system

### Security

- Added authentication for worker API endpoints
- API key generation and management
- Secure key storage with restricted permissions

## [0.1.0] - 2026-01-15

### Added

- Initial MVP release
- Core coordinator/worker architecture
- Job queue management
- Frame chunking and distribution
- Heartbeat-based health monitoring
