# WeRender API Reference

This document provides an overview of the WeRender HTTP and WebSocket APIs.

## Base URL

The Coordinator exposes its API at:
```
http://<coordinator-ip>:8420
```

## Authentication

Worker endpoints require an API key in the `X-API-Key` header:
```http
X-API-Key: your_worker_api_key
```

See the [Security Guide](../security/SECURITY_GUIDE.md) for setup details.

---

## HTTP Endpoints

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/jobs` | List all jobs |
| `POST` | `/api/jobs` | Create a new job |
| `GET` | `/api/jobs/{job_id}` | Get job details |
| `POST` | `/api/jobs/{job_id}/start` | Start a job |
| `POST` | `/api/jobs/{job_id}/pause` | Pause a job |
| `DELETE` | `/api/jobs/{job_id}` | Delete a job |
| `GET` | `/api/jobs/{job_id}/blend` | Download blend file (auth required) |

### Tasks

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/tasks/request` | ✅ | Request next available task |
| `POST` | `/api/tasks/{task_id}/complete` | ✅ | Upload completed frame |
| `POST` | `/api/tasks/{task_id}/fail` | ✅ | Report task failure |

### Workers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/workers` | List connected workers |

---

## WebSocket

### Endpoint
```
ws://<coordinator-ip>:8420/ws
```

### Message Types

**Worker → Coordinator:**
- `heartbeat` - Worker status and resource usage
- `log` - Render progress logs

**Coordinator → Worker:**
- `job_update` - New job available
- `cancel` - Cancel current task

---

## Dashboard

The web dashboard is served at the root URL:
```
http://<coordinator-ip>:8420/
```

Access from any browser on the network to monitor render progress.
