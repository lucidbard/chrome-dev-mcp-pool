# Dual-Mode Chrome Support

Chrome Pool Manager supports two modes for running Chrome instances:

## Headless Mode (WSL)

**Best for:**
- Automated testing
- CI/CD pipelines
- Background tasks
- Fast startups
- Server-side rendering
- Screenshot capture without GUI

**How it works:**
- Chrome runs directly on WSL with `--headless=new` flag
- No browser window visible
- Debugging port accessible on WSL localhost
- Fast startup (~2 seconds)

**Request:**
```json
{
  "agent_id": "my-agent",
  "url": "http://localhost:3000",
  "mode": "headless"
}
```

## GUI Mode (Windows)

**Best for:**
- Collaborative debugging
- User demonstrations
- Visual verification
- Interactive testing
- Real-time observation
- User can see and interact with browser

**How it works:**
1. Service sends SSH command to Windows to start Chrome with GUI
2. Chrome window appears on Windows desktop
3. SSH tunnel forwards debugging port from Windows to WSL
4. Agent connects through tunnel on WSL side
5. Both agent and user can interact with same browser

**Request:**
```json
{
  "agent_id": "my-agent",
  "url": "http://192.168.1.86:3000",
  "mode": "gui"
}
```

## Usage Examples

### Via MCP Tools

**Headless (default):**
```javascript
// For automated testing
use_mcp_tool("chrome-manager", "request_chrome_instance", {
  agent_id: "test-runner-123",
  url: "http://localhost:3000",
  mode: "headless"  // optional, this is the default
});
```

**GUI (for demos):**
```javascript
// When user needs to see the browser
use_mcp_tool("chrome-manager", "request_chrome_instance", {
  agent_id: "demo-agent-456",
  url: "http://192.168.1.86:3000",
  mode: "gui"  // visible Chrome window on Windows
});
```

### Via HTTP API

**Headless:**
```bash
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "url": "http://localhost:3000",
    "mode": "headless",
    "timeout": 300
  }'
```

**GUI:**
```bash
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "url": "http://192.168.1.86:3000",
    "mode": "gui",
    "timeout": 600
  }'
```

## Architecture Comparison

### Headless Mode
```
┌─────────────────────────────────────────┐
│ WSL: Chrome (headless)                  │
│ - Port 9222 directly accessible         │
│ - No GUI                                │
└─────────────────────────────────────────┘
                 ↑
                 │ Direct connection
                 │
┌─────────────────────────────────────────┐
│ WSL: Agent                              │
│ - Connects to localhost:9222            │
└─────────────────────────────────────────┘
```

### GUI Mode
```
┌─────────────────────────────────────────┐
│ Windows: Chrome (GUI visible)           │
│ - Port 9222 on Windows localhost        │
│ - User can see and interact             │
└─────────────────────────────────────────┘
                 ↑ SSH tunnel
                 ↓
┌─────────────────────────────────────────┐
│ WSL: SSH Tunnel                         │
│ - Forwards port 9222                    │
└─────────────────────────────────────────┘
                 ↑
                 │ Local connection
                 │
┌─────────────────────────────────────────┐
│ WSL: Agent                              │
│ - Connects to localhost:9222            │
│ - Same API as headless mode             │
└─────────────────────────────────────────┘
```

## Performance Characteristics

| Metric | Headless | GUI |
|--------|----------|-----|
| Startup Time | ~2 seconds | ~5 seconds |
| Memory Usage | ~150MB | ~200MB |
| CPU Usage | Low | Medium |
| Network Latency | None | SSH overhead (~5ms) |
| User Visibility | None | Full visibility |
| User Interaction | No | Yes |

## Use Case Matrix

| Scenario | Recommended Mode |
|----------|------------------|
| Unit tests | Headless |
| E2E tests (automated) | Headless |
| Screenshot capture | Headless |
| Performance testing | Headless |
| CI/CD pipeline | Headless |
| Bug reproduction | GUI |
| User demonstration | GUI |
| Collaborative debugging | GUI |
| Teaching/training | GUI |
| Visual QA review | GUI |

## Configuration

### Headless Mode (WSL)
```python
# In chrome_pool_service.py
CHROME_PATH_WSL = "/usr/bin/google-chrome"
```

Chrome must be installed on WSL:
```bash
sudo apt-get install google-chrome-stable
```

### GUI Mode (Windows)
```python
# In chrome_pool_service.py
CHROME_PATH_WINDOWS = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
WINDOWS_HOST = "stark-windows"  # SSH hostname
```

Requirements:
- Chrome installed on Windows
- SSH access to Windows configured
- `stark-windows` in SSH config

## Troubleshooting

### Headless Mode Issues

**Problem:** Chrome won't start
```bash
# Check Chrome installed
which google-chrome

# Test Chrome manually
google-chrome --version
google-chrome --headless=new --remote-debugging-port=9999 about:blank &
curl http://localhost:9999/json/version
pkill chrome
```

**Problem:** Permission denied
- Add `--no-sandbox` flag (already included)
- Check file permissions on user data dir

### GUI Mode Issues

**Problem:** Chrome window doesn't appear on Windows
```bash
# Test SSH to Windows
ssh stark-windows "powershell -Command 'echo test'"

# Test Chrome start manually
ssh stark-windows "powershell -Command \"Start-Process 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' -ArgumentList '--version'\""
```

**Problem:** SSH tunnel fails
```bash
# Check tunnel exists
ps aux | grep "ssh.*9222"

# Test tunnel manually
ssh -L 9222:127.0.0.1:9222 stark-windows
# In another terminal:
curl http://localhost:9222/json/version
```

**Problem:** Port already in use
```bash
# Kill existing tunnel
pkill -f "ssh.*9222"

# Or kill specific tunnel
kill <tunnel_pid>
```

## Switching Between Modes

The pool manager handles mode switching automatically. You can have:
- 5 instances in headless mode
- 3 instances in GUI mode
- All running simultaneously on different ports

Each instance tracks its mode in the database.

## Best Practices

1. **Use headless by default** - Faster and more efficient
2. **Switch to GUI when needed** - Only for demos/debugging
3. **Release GUI instances promptly** - More resource-intensive
4. **Set appropriate timeouts** - GUI mode may need longer timeouts
5. **Check mode in status** - Use `get_instance_status` to verify mode

## Example Workflow

**Automated Testing:**
```javascript
// Fast headless testing
const instance = await request_chrome_instance({
  agent_id: "test-123",
  mode: "headless"
});
// Run tests...
await release_chrome_instance({instance_id: instance.instance_id});
```

**Bug Demonstration:**
```javascript
// Switch to GUI to show bug to user
const instance = await request_chrome_instance({
  agent_id: "demo-456",
  url: "http://app.test/broken-page",
  mode: "gui",
  timeout: 600  // 10 minutes for demo
});
// User can now see the browser on Windows desktop
// Agent can take screenshots, user can interact
// Both see the same browser
await release_chrome_instance({instance_id: instance.instance_id});
```

## Security Considerations

**Headless Mode:**
- Runs with `--no-sandbox` (required for WSL)
- Isolated user data directories per instance
- No network access to host system

**GUI Mode:**
- Requires SSH access to Windows
- Chrome runs with full Windows privileges
- User can see all browser activity
- Consider this when handling sensitive data

## Future Enhancements

Potential improvements:
- VNC mode (headless with remote viewing)
- Recording mode (capture video of GUI sessions)
- Shared mode (multiple agents, one GUI)
- Remote mode (Chrome on different machine)
