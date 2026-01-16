# WeRender Security Guide

## Overview

WeRender now includes a robust API key-based authentication system to secure communications between coordinators and workers. This guide explains how the security works and how to configure it properly.

## Authentication System

### How It Works

WeRender uses API key authentication with the following features:

1. **Secure Key Generation**: API keys are generated using Python's `secrets` module, which provides cryptographically strong random numbers suitable for security applications.

2. **Automatic Key Creation**: When the coordinator starts for the first time, it automatically generates:
   - A coordinator key (for administrative functions)
   - A worker key (for worker nodes)

3. **Key Storage**: Keys are stored in `~/.werender/api_keys.json` with restrictive permissions on Unix-like systems (chmod 600).

4. **HTTP Header Authentication**: Workers authenticate by including their API key in the `X-API-Key` HTTP header with every request.

5. **Environment Variable Support**: Workers can receive their API key via the `WERENDER_API_KEY` environment variable, which is ideal for containerized deployments.

## Setup Instructions

### Initial Setup

1. **Start the Coordinator**:
   ```bash
   python -m werender.main coordinator
   ```

   The coordinator will automatically generate API keys on first startup and display setup instructions.

2. **Note the Worker API Key**:
   The coordinator will print the worker API key. Keep this secure!

3. **Configure Workers**:
   
   **Option A: Environment Variable (Recommended for production)**
   ```bash
   export WERENDER_API_KEY="your_worker_api_key_here"
   python -m werender.main worker
   ```

   **Option B: Shared Config Directory**
   Copy `api_keys.json` from the coordinator's `~/.werender/` directory to each worker's `~/.werender/` directory.

   **Option C: Docker/Container**
   Pass the API key as an environment variable:
   ```bash
   docker run -e WERENDER_API_KEY="your_worker_api_key_here" ...
   ```

## Security Best Practices

### For Local Networks

Even on local networks, proper authentication is important because:

1. **Prevent Unauthorized Access**: Without authentication, anyone on your local network could:
   - Submit malicious render jobs
   - Access your blend files
   - Corrupt render results
   - Exhaust system resources

2. **Network Segmentation**: Local networks aren't always as secure as they seem:
   - Guest networks may have access
   - IoT devices can be compromised
   - Network misconfigurations can expose services unexpectedly

3. **Preparation for Remote Access**: Having authentication in place makes it safer if you later need to access the system remotely.

### Production Deployment

When deploying in production environments:

1. **Use Unique Keys per Worker**:
   ```python
   from werender.network.auth import AuthManager
   
   auth = AuthManager()
   unique_key = auth.add_worker_key("worker_host_01")
   print(f"New worker key: {unique_key}")
   ```

2. **Rotate Keys Regularly**:
   ```python
   auth.revoke_key("worker_host_01")
   new_key = auth.add_worker_key("worker_host_01")
   ```

3. **Never Commit API Keys**:
   Add to `.gitignore`:
   ```
   .werender/api_keys.json
   ```

4. **Use Environment Variables**:
   Never hardcode API keys in scripts or configuration files.

5. **Monitor Access Logs**:
   The coordinator logs all worker connections and failures. Monitor for:
   - Repeated authentication failures (possible brute force attacks)
   - Connections from unexpected IP addresses
   - Unusual activity patterns

6. **Network Isolation**:
   - Use firewalls to restrict access to coordinator ports
   - Consider placing coordinators and workers on a dedicated network segment
   - Use VPN for remote access

## API Endpoints Security

### Protected Endpoints

The following endpoints require worker authentication:

- `GET /api/tasks/request` - Request render tasks
- `POST /api/tasks/{task_id}/complete` - Upload rendered frames
- `POST /api/tasks/{task_id}/fail` - Report task failures
- `GET /api/jobs/{job_id}/blend` - Download blend files

### Unprotected Endpoints

These endpoints remain publicly accessible (for now):

- Job management endpoints (create, start, pause, etc.)
- Worker listing endpoint
- Synchronization endpoints
- WebSocket endpoint for dashboard

**Future Enhancement**: In a future update, these can be protected with separate authentication for web dashboard users.

## Troubleshooting

### "API key required" Error

**Symptom**: Worker receives 401 Unauthorized when requesting tasks.

**Solution**: Ensure the worker has access to the API key:
```bash
# Check if environment variable is set
echo $WERENDER_API_KEY

# Or verify api_keys.json exists
ls ~/.werender/api_keys.json
```

### "Invalid API key" Error

**Symptom**: Worker receives 403 Forbidden.

**Solutions**:
1. Verify the API key matches the one from the coordinator
2. Check that the key hasn't been revoked
3. Ensure you're using the worker key, not the coordinator key

### Worker Cannot Find API Key

**Symptom**: Worker prints error message about missing API key.

**Solution**: Follow one of the setup options above to provide the API key to the worker.

## Advanced Configuration

### Adding Custom Key Types

The authentication system is extensible. You can add custom key types:

```python
from werender.network.auth import AuthManager

auth = AuthManager()

# Add a custom key type
auth.api_keys["manager"] = "your_custom_key_here"
auth._save_api_keys(auth.api_keys)

# Create a dependency for this key type
manager_auth = get_api_key_dependency(auth, "manager")
```

### Implementing Rate Limiting

You can add rate limiting on top of authentication to prevent abuse:

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Add to FastAPI app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to endpoints
@app.get("/api/tasks/request", 
         dependencies=[Depends(worker_auth)])
@limiter.limit("10/minute")
async def request_task(...):
    ...
```

## Security Audits

Regular security audits are recommended:

1. **Check API Key Usage**:
   ```python
   import json
   
   with open("~/.werender/api_keys.json") as f:
       keys = json.load(f)
   
   print(f"Total keys: {len(keys)}")
   print(f"Key types: {list(keys.keys())}")
   ```

2. **Review Access Logs**: Check coordinator logs for suspicious activity.

3. **Update Dependencies**: Keep Python packages updated:
   ```bash
   pip install --upgrade -r requirements.txt
   ```

4. **Network Scanning**: Use tools like `nmap` to verify only expected ports are accessible.

## Compliance Considerations

If you're using WeRender in an environment with security compliance requirements:

- **GDPR**: The authentication system itself doesn't store personal data, but blend files might.
- **HIPAA**: Ensure render farms handling medical data have proper access controls.
- **SOC 2**: Implement additional audit logging and access controls.

## Conclusion

The WeRender authentication system provides a strong foundation for securing your distributed rendering operations. By following the best practices outlined in this guide, you can ensure your render farm remains secure while maintaining ease of use.

For questions or security concerns, please open an issue on the WeRender GitHub repository.