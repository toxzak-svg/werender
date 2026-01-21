# WeRender Security Guide

## Overview

This document describes the security measures implemented in WeRender to prevent Remote Code Execution (RCE) attacks and other security vulnerabilities.

## Critical Security Issue (RESOLVED)

### The Problem

WeRender previously allowed **unauthenticated access** to critical endpoints, enabling a serious RCE vulnerability:

1. **No authentication on job creation** - Anyone could upload .blend files
2. **No .blend file validation** - Malicious .blend files could execute arbitrary code
3. **No authentication on management endpoints** - Anyone could control jobs
4. **No authentication on sync endpoints** - Anyone could download settings/addons

### Attack Vector

A malicious actor could:
1. Discover a WeRender coordinator via mDNS
2. Upload a malicious .blend file containing Python code
3. Workers would automatically render the file, executing the malicious code
4. This provides remote code execution on all connected workers

### The Fix

We've implemented comprehensive security measures:

## 1. API Key Authentication

### Overview

All API endpoints now require authentication using API keys stored in `~/.werender/api_keys.json`.

### API Key Types

- **Coordinator Key**: Required for job management and administrative operations
- **Worker Key**: Required for workers to receive tasks and upload results

### API Key Management

**Automatic Generation**

When you first start the coordinator, API keys are automatically generated:

```python
from werender.network.auth import AuthManager

auth_manager = AuthManager()
auth_manager.print_setup_instructions()
```

**Output:**
```
============================================================
WeRender Authentication Setup
============================================================

API keys have been generated and stored in:
  /home/user/.werender/api_keys.json

Workers must be configured with the worker API key:
  Worker API Key: 7f8e9d3a...

For production use, you should:
  1. Keep API keys secret and never commit to version control
  2. Use environment variables for worker deployment
  3. Generate unique keys for each worker using add_worker_key()
  4. Regularly rotate keys using revoke_key() and generate new ones
============================================================
```

**Manual Key Management**

```python
from werender.network.auth import AuthManager

auth_manager = AuthManager()

# Generate a unique key for a specific worker
worker_key = auth_manager.add_worker_key("worker_host_01")
print(f"New worker key: {worker_key}")

# Revoke a compromised key
auth_manager.revoke_key("worker_host_01")
```

**Environment Variable**

Workers can use the `WERENDER_API_KEY` environment variable:

```bash
export WERENDER_API_KEY="your_worker_api_key_here"
python -m werender.main worker
```

### Protected Endpoints

**Coordinator Authentication Required:**
- `POST /api/jobs/create` - Create new render jobs
- `GET /api/jobs` - List all jobs
- `GET /api/jobs/{job_id}` - Get job details
- `PATCH /api/jobs/{job_id}` - Update job properties
- `POST /api/jobs/{job_id}/start` - Start a job
- `POST /api/jobs/{job_id}/pause` - Pause a job
- `POST /api/jobs/{job_id}/resume` - Resume a job
- `POST /api/jobs/{job_id}/cancel` - Cancel a job
- `POST /api/jobs/{job_id}/reload_blend` - Reload blend file
- `GET /api/workers` - List connected workers

**Worker Authentication Required:**
- `GET /api/tasks/request` - Request tasks
- `POST /api/tasks/{task_id}/complete` - Upload completed task
- `POST /api/tasks/{task_id}/fail` - Report task failure
- `GET /api/jobs/{job_id}/blend` - Download blend file
- `GET /api/sync/manifest` - Get sync manifest
- `GET /api/sync/settings` - Get settings
- `GET /api/sync/addons` - List addons
- `GET /api/sync/addons/{addon_name}/download` - Download addon

### Using API Keys

**curl example:**
```bash
# Create a job (requires coordinator key)
curl -X POST http://coordinator:8420/api/jobs/create \
  -H "X-API-Key: your_coordinator_key" \
  -F "file=@scene.blend" \
  -F "frame_start=1" \
  -F "frame_end=100" \
  -F "name=My Project"
```

**Python example:**
```python
import requests

headers = {"X-API-Key": "your_coordinator_key"}

# Create a job
with open("scene.blend", "rb") as f:
    response = requests.post(
        "http://coordinator:8420/api/jobs/create",
        headers=headers,
        files={"file": f},
        data={
            "frame_start": 1,
            "frame_end": 100,
            "name": "My Project"
        }
    )
```

## 2. .blend File Validation

### Overview

All uploaded .blend files are validated before being accepted for rendering.

### Validation Checks

1. **File Extension** - Must end with `.blend`
2. **File Size** - Maximum 500 MB
3. **Magic Bytes** - Must start with `BLENDER` header
4. **Header Structure** - Valid pointer size, endianness, and version
5. **Filename Sanitization** - Path traversal prevention

### Implementation

```python
from werender.network.security import BlendFileValidator

# Validate a file
is_valid, error = BlendFileValidator.validate_blend_file(Path("scene.blend"))
if not is_valid:
    print(f"Invalid file: {error}")
```

### Security Benefits

- **Prevents malicious file uploads** - Invalid files are rejected
- **Prevents path traversal** - Filenames are sanitized
- **Prevents DoS** - File size limits enforced
- **Detects corrupted files** - Header validation

### Validation Details

**Magic Bytes Check:**
```
BLENDER_v294
^^^^^^^     ^
|           |
|           Version (e.g., 294)
|
File type identifier
```

**Header Fields:**
- Magic: `BLENDER` (7 bytes)
- Pointer size: `_` (32-bit) or `-` (64-bit)
- Endianness: `v` (little-endian) or `V` (big-endian)
- Version: 3-digit version number

## 3. Rate Limiting

### Overview

Rate limiting prevents brute-force attacks and abuse of the API.

### Configuration

```python
from werender.network.security import RateLimiter

# Allow 10 requests per 60 seconds per client
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Check if request is allowed
if rate_limiter.is_allowed(client_ip):
    # Process request
    pass
else:
    # Rate limit exceeded
    raise HTTPException(status_code=429, detail="Too many requests")
```

### Benefits

- **Prevents brute-force attacks** on API keys
- **Prevents DoS attacks** through excessive requests
- **Protects against automated abuse**

## 4. Security Best Practices

### For Development

1. **Never commit API keys** to version control
2. **Use environment variables** for sensitive configuration
3. **Rotate API keys regularly**
4. **Monitor logs** for authentication failures
5. **Use firewall rules** to restrict access

### For Production Deployment

1. **Network Isolation**
   ```bash
   # Use firewall to restrict access to coordinator
   sudo ufw allow from 10.0.0.0/8 to any port 8420
   sudo ufw enable
   ```

2. **VPN or Private Network**
   - Deploy WeRender on a private network
   - Use VPN for remote access
   - Avoid exposing coordinator to public internet

3. **HTTPS/TLS** (future enhancement)
   - Use HTTPS for encrypted communication
   - Install valid SSL certificates
   - Enforce HTTPS only

4. **API Key Rotation**
   ```bash
   # Monthly key rotation
   python -c "from werender.network.auth import AuthManager; AuthManager().print_setup_instructions()"
   ```

5. **File System Permissions**
   ```bash
   # Restrict API key file permissions
   chmod 600 ~/.werender/api_keys.json
   ```

6. **Network Segmentation**
   - Separate coordinator and worker networks
   - Use VLANs or network ACLs
   - Minimize attack surface

7. **Monitoring and Logging**
   - Monitor authentication failures
   - Alert on suspicious activity
   - Regular security audits

### For Workers

1. **Secure API Key Storage**
   ```bash
   # Use environment variable
   export WERENDER_API_KEY="your_key"
   ```

2. **Run as Non-Root User**
   ```bash
   # Create dedicated user
   sudo useradd -r -s /bin/false werender
   sudo -u werender python -m werender.main worker
   ```

3. **Sandboxing** (recommended for production)
   - Use containers (Docker, Podman)
   - Use virtual machines
   - Limit filesystem access

4. **Resource Limits**
   ```bash
   # Set memory and CPU limits
   ulimit -v 8388608  # 8GB RAM
   ```

## 5. Security Checklist

### Before Deployment

- [ ] Generate unique API keys
- [ ] Configure firewall rules
- [ ] Set up network isolation
- [ ] Configure rate limiting
- [ ] Enable logging and monitoring
- [ ] Review file permissions
- [ ] Test authentication
- [ ] Test file validation
- [ ] Document API key storage
- [ ] Set up key rotation schedule

### Regular Maintenance

- [ ] Monitor authentication logs weekly
- [ ] Rotate API keys monthly
- [ ] Review security advisories
- [ ] Update WeRender regularly
- [ ] Audit access logs monthly
- [ ] Test security controls quarterly
- [ ] Review firewall rules quarterly
- [ ] Update SSL certificates annually

### Incident Response

If you suspect a security breach:

1. **Immediate Actions**
   - Revoke all API keys immediately
   - Stop the coordinator server
   - Disconnect workers from network
   - Preserve logs for analysis

2. **Investigation**
   - Review authentication logs
   - Check for unauthorized job submissions
   - Analyze network traffic
   - Identify affected systems

3. **Recovery**
   - Generate new API keys
   - Rotate all credentials
   - Patch vulnerabilities
   - Restore from clean backup

4. **Post-Incident**
   - Document the incident
   - Update security procedures
   - Conduct security audit
   - Train team members

## 6. Common Security Issues and Solutions

### Issue: Workers cannot authenticate

**Symptoms:**
```
❌ Error: No API key found
```

**Solutions:**
```bash
# Option 1: Copy API keys from coordinator
scp ~/.werender/api_keys.json user@worker:~/.werender/

# Option 2: Use environment variable
export WERENDER_API_KEY="your_key_here"

# Option 3: Generate new worker-specific key
python -c "from werender.network.auth import AuthManager; print(AuthManager().add_worker_key('worker_01'))"
```

### Issue: Authentication fails with 403

**Symptoms:**
```
HTTP 403: Invalid API key
```

**Solutions:**
- Verify API key is correct
- Check you're using the right key type (coordinator vs worker)
- Ensure key hasn't been revoked
- Check key hasn't been rotated

### Issue: File upload rejected

**Symptoms:**
```
HTTP 400: Invalid .blend file: missing magic bytes
```

**Solutions:**
- Verify file is a valid .blend file
- Check file wasn't corrupted during upload
- Ensure file size < 500 MB
- Try re-exporting from Blender

### Issue: Rate limit exceeded

**Symptoms:**
```
HTTP 429: Too many requests
```

**Solutions:**
- Reduce request frequency
- Implement exponential backoff
- Contact admin to increase limits

## 7. Future Security Enhancements

Planned security improvements:

1. **JWT Token Authentication** - More secure than API keys
2. **TLS/HTTPS Support** - Encrypted communications
3. **IP Whitelisting** - Restrict access by IP address
4. **Multi-Factor Authentication** - Additional security layer
5. **Audit Logging** - Detailed security event logs
6. **Sandbox Execution** - Isolate worker processes
7. **File Hash Verification** - Detect tampered files
8. **Webhook Security** - Signed webhook payloads

## 8. Reporting Security Issues

If you discover a security vulnerability:

1. **Do not** create a public issue
2. **Do** email security reports privately
3. **Include** detailed reproduction steps
4. **Allow** time for fix before disclosure
5. **Follow** responsible disclosure practices

Contact: [security@example.com]

## 9. Security References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE-94: Code Injection](https://cwe.mitre.org/data/definitions/94.html)
- [CWE-287: Improper Authentication](https://cwe.mitre.org/data/definitions/287.html)

## 10. Changelog

### Version 1.1.0 (Security Update)
- ✅ Added API key authentication to all endpoints
- ✅ Implemented .blend file validation
- ✅ Added filename sanitization
- ✅ Implemented rate limiting
- ✅ Added security documentation
- ✅ Fixed RCE vulnerability (CVE-2024-XXXX)

### Version 1.0.0
- Initial release (had security vulnerabilities)