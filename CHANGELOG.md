# Changelog

All notable changes to WeRender will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Enhanced dashboard UI with per-frame progress visualization
- Performance metrics and benchmarking tools
- Cloud worker support (AWS, GCP, Azure)
- Priority queuing for multiple concurrent jobs
- GPU/CPU selection per worker
- Mobile app for monitoring

## [0.2.0-beta] - 2026-01-21

### Added

- API key-based authentication system for secure worker communication
- Comprehensive security guide documentation
- Fault tolerance and worker recovery features
- Worker authentication via environment variables
- Detailed "Why WeRender" section with value proposition
- Real-world example scenarios (indie studio, classroom, VFX shop, freelancer)
- End-to-end Quick Start walkthrough with expected outputs
- Demo project link for testing without user files
- Project status section with maturity level and known limitations
- Community & support section with contribution guidelines
- Enhanced feature descriptions with security and reliability emphasis

### Security

- Added authentication for worker API endpoints
- API key generation and management using cryptographically strong random numbers
- Secure key storage with restricted permissions (chmod 600 on Unix)
- HTTP header authentication via X-API-Key header
- Environment variable support for API keys (WERENDER_API_KEY)
- Security best practices documentation

### Documentation

- Added comprehensive Security Guide
- Enhanced README with use cases and examples
- Updated project status and roadmap
- Added contribution guidelines with priority areas

### Changed

- Improved error messages for missing API keys
- Enhanced logging for worker connection attempts
- Better handling of network interruptions

### Fixed

- Workers now properly re-authenticate after coordinator restart
- Frame reassignment with exponential backoff to prevent cascading failures

## [0.1.0] - 2026-01-15

### Added

- Initial MVP release
- Core coordinator/worker architecture
- Job queue management
- Frame chunking and distribution
- Heartbeat-based health monitoring