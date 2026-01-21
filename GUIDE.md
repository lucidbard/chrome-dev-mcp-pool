# Chrome Pool Manager - Complete Guide

**Version:** 1.0.0
**Status:** ✅ Fully Operational (Headless + GUI modes)
**Test Results:** 22/23 passing (95.7%) - See [TEST-RESULTS.md](TEST-RESULTS.md)
**Location:** `/home/john/chrome-pool-manager/`

---

## Overview

Chrome Pool Manager solves the problem of multiple AI agents needing Chrome instances simultaneously. Instead of conflicts over port 9222, agents request instances from a pool (ports 9222-9232) and get dedicated, isolated Chrome instances.

### Key Features

- **Port Pool Management**: 11 Chrome instances (ports 9222-9232)
- **Dual-Mode Support**: Headless (WSL) or GUI (Windows) Chrome
- **Resource Isolation**: Each agent gets dedicated Chrome instance
- **Auto-Cleanup**: Expired allocations automatically released
- **MCP Integration**: 6 MCP tools for AI agents
- **System Service**: Runs automatically via systemd
- **State Persistence**: SQLite database tracks all instances

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ AI Agent (Claude Code, etc.)                                │
│ - Requests Chrome instance                                  │
│ - Gets dedicated debug port                                 │
└─────────────────────────────────────────────────────────────┘
                         ↓ MCP Protocol (stdio)
┌─────────────────────────────────────────────────────────────┐
│ MCP Server (chrome-manager-mcp.service)                     │
│ Location: ~/chrome-pool-manager/mcp-server/                 │
│ - 6 MCP tools exposed to agents                             │
│ - HTTP client to pool service                               │
└─────────────────────────────────────────────────────────────┘
                         ↓ HTTP
┌─────────────────────────────────────────────────────────────┐
│ Pool Service (chrome-pool.service)                          │
│ Location: ~/chrome-pool-manager/pool-service/               │
│ Endpoint: http://localhost:8765                             │
│ - Manages 11 Chrome instances (ports 9222-9232)             │
│ - Allocates/releases instances                              │
│ - Auto-cleanup of expired instances                         │
│ - SQLite state persistence                                  │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────┬──────────────────────────────────┐
│ Headless Mode (WSL)      │ GUI Mode (Windows)               │
│ - Fast, background       │ - Visible Chrome window          │
│ - Direct subprocess      │ - Windows Scheduled Task         │
│ - Best for automation    │ - SSH tunnel for debug port      │
│                          │ - Best for demos/debugging       │
└──────────────────────────┴──────────────────────────────────┘
```

---

## Dual-Mode Support

### Headless Mode (Default)

**When to Use:**
- Automated testing
- Background tasks
- CI/CD pipelines
- Fast iteration
- Multiple parallel instances

**How It Works:**
```
Agent → MCP → Pool Service → Chrome (headless on WSL)
```

**Characteristics:**
- Chrome runs with `--headless=new` flag on WSL
- No GUI window visible
- Debug port directly accessible at `localhost:PORT`
- Startup: ~2 seconds
- Low resource usage

**Example:**
```bash
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test-agent", "mode": "headless"}'
```

### GUI Mode

**When to Use:**
- Demonstrations
- Debugging visual issues
- Collaborative development (user + agent see same browser)
- Presentations
- Interactive tutorials

**How It Works:**
```
Agent → MCP → Pool Service → SSH → Windows → Chrome (GUI)
                                  ↓
                            SSH Tunnel ← Debug Port
```

**Characteristics:**
- Chrome window visible on Windows desktop
- Windows Scheduled Task runs in interactive session
- SSH tunnel forwards debug port to WSL
- User and agent both see/control same browser
- Startup: ~7 seconds
- Moderate resource usage

**Example:**
```bash
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "demo-agent", "url": "http://google.com", "mode": "gui"}'
```

---

## Installation & Setup

### Prerequisites

**For Headless Mode:**
- Chrome installed on WSL: `google-chrome-stable`
- WSL with systemd support

**For GUI Mode:**
- Chrome installed on Windows (standard installation)
- SSH access to Windows (host: `stark-windows`)
- SSH key authentication configured
- Windows OpenSSH server running

### Services

Two systemd user services run automatically:

**1. chrome-pool.service**
- Pool manager (FastAPI HTTP server)
- Location: `~/.config/systemd/user/chrome-pool.service`
- Manages Chrome instances
- Endpoint: `http://localhost:8765`

**2. chrome-manager-mcp.service**
- Note: This service file exists but should NOT be started as systemd service
- MCP servers run on-demand via stdio when invoked by Claude Code
- Only used via MCP configuration in `mcp_config.json`

### Service Commands

```bash
# Check pool service status
systemctl --user status chrome-pool

# Restart pool service
systemctl --user restart chrome-pool

# View logs
journalctl --user -u chrome-pool -f

# Enable auto-start
systemctl --user enable chrome-pool
```

---

## MCP Integration

### Configuration

Add to `~/.config/claude-code/mcp_config.json`:

```json
{
  "mcpServers": {
    "chrome-manager": {
      "command": "/home/john/chrome-pool-manager/mcp-server/venv/bin/python",
      "args": ["/home/john/chrome-pool-manager/mcp-server/chrome_manager_mcp.py"]
    }
  }
}
```

### Available MCP Tools

**1. request_chrome_instance**
- Allocate a Chrome instance from the pool
- Parameters:
  - `agent_id` (required): Unique identifier for your agent
  - `url` (optional): URL to load, default: "about:blank"
  - `timeout` (optional): Allocation timeout in seconds, default: 300
  - `mode` (optional): "headless" or "gui", default: "headless"
- Returns: `{instance_id, debug_port, agent_id, expires_at}`

**2. release_chrome_instance**
- Release a Chrome instance back to the pool
- Parameters:
  - `instance_id` (required): Instance to release

**3. get_instance_status**
- Check status of a specific instance
- Parameters:
  - `instance_id` (required): Instance to check

**4. list_chrome_instances**
- List all instances in the pool
- No parameters
- Returns: Array of all instances with their status

**5. send_heartbeat**
- Keep instance alive (extends expiration)
- Parameters:
  - `instance_id` (required): Instance to keep alive

**6. stream_pool_status**
- HTTP stream of real-time pool updates
- Parameters:
  - `duration` (optional): Stream duration in seconds, default: 30

### Usage Pattern

```
1. Request instance → get debug_port (e.g., 9227)
2. Use chrome-devtools MCP with localhost:<debug_port>
3. Interact with browser (navigate, screenshot, etc.)
4. Release instance when done
```

---

## HTTP API Reference

### Base URL
```
http://localhost:8765
```

### Endpoints

**GET /health**
```bash
curl http://localhost:8765/health
# Returns: {"status": "healthy"}
```

**GET /instances**
```bash
curl http://localhost:8765/instances
# Returns: Array of all instances
```

**POST /instance/allocate**
```bash
# Headless mode
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-agent", "mode": "headless"}'

# GUI mode
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-agent", "url": "http://google.com", "mode": "gui"}'

# Returns: {"instance_id": "chrome-9222", "debug_port": 9222, ...}
```

**POST /instance/{instance_id}/release**
```bash
curl -X POST http://localhost:8765/instance/chrome-9222/release

# Returns: {"status": "released", "instance_id": "chrome-9222"}
```

**GET /instance/{instance_id}/status**
```bash
curl http://localhost:8765/instance/chrome-9222/status

# Returns: {"instance_id": "chrome-9222", "status": "allocated", ...}
```

**POST /instance/{instance_id}/heartbeat**
```bash
curl -X POST http://localhost:8765/instance/chrome-9222/heartbeat

# Returns: {"status": "heartbeat_received", "new_expires_at": "..."}
```

---

## Testing & Verification

### Test Headless Mode

```bash
# 1. Allocate headless instance
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test-headless"}'

# 2. Test debug port (use port from response)
curl http://localhost:9222/json/version

# 3. Check Chrome process
ps aux | grep chrome | grep headless

# 4. Release instance
curl -X POST http://localhost:8765/instance/chrome-9222/release
```

### Test GUI Mode

```bash
# 1. Allocate GUI instance
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test-gui", "url": "http://google.com", "mode": "gui"}'

# 2. Check Chrome window appeared on Windows desktop (visual check)

# 3. Test debug port through tunnel
curl http://localhost:9227/json/version

# 4. Check SSH tunnel
ps aux | grep "ssh.*-L.*9227"

# 5. Release instance
curl -X POST http://localhost:8765/instance/chrome-9227/release

# 6. Verify cleanup
# - Chrome window closed
# - SSH tunnel killed
# - Scheduled task deleted
```

### Test with chrome-devtools MCP

```bash
# 1. Request instance via chrome-manager MCP
# agent_id: "devtools-test", mode: "gui"

# 2. Use chrome-devtools MCP tools with returned debug_port
# - list_pages
# - navigate_page
# - take_snapshot
# - take_screenshot

# 3. Release instance
```

---

## Troubleshooting

### Pool Service Not Starting

```bash
# Check status
systemctl --user status chrome-pool

# View logs
journalctl --user -u chrome-pool -n 50

# Common issues:
# - Chrome not installed: sudo apt-get install google-chrome-stable
# - Port 8765 in use: lsof -i :8765
# - Database locked: rm ~/chrome-pool-manager/pool-service/chrome_pool.db
```

### GUI Mode Not Working

```bash
# 1. Test SSH connection to Windows
ssh stark-windows "echo OK"

# 2. Check if Chrome installed on Windows
ssh stark-windows "powershell -Command 'Test-Path \"C:\Program Files\Google\Chrome\Application\chrome.exe\"'"

# 3. Test scheduled task creation manually
ssh stark-windows "schtasks /Create /TN TestTask /TR 'notepad.exe' /SC ONCE /ST 00:00 /F"
ssh stark-windows "schtasks /Run /TN TestTask"
ssh stark-windows "schtasks /Delete /TN TestTask /F"

# 4. Check SSH tunnel
ps aux | grep "ssh.*-L"
```

### Instance Stuck in "allocated" State

```bash
# Check if Chrome process still running
ps aux | grep chrome | grep "<port>"

# Force cleanup by restarting service
systemctl --user restart chrome-pool
```

### Debug Port Not Accessible

```bash
# Check Chrome is listening
curl http://localhost:<port>/json/version

# For GUI mode, check tunnel
ps aux | grep "ssh.*-L.*<port>"

# Test on Windows directly
ssh stark-windows "powershell -Command 'Test-NetConnection -ComputerName localhost -Port <port>'"
```

---

## File Structure

```
/home/john/chrome-pool-manager/
├── pool-service/
│   ├── chrome_pool_service.py       # Main pool manager (FastAPI)
│   ├── requirements.txt
│   ├── venv/                         # Python virtual environment
│   └── chrome_pool.db               # SQLite database
│
├── mcp-server/
│   ├── chrome_manager_mcp.py        # MCP server (stdio)
│   ├── requirements.txt
│   └── venv/                         # Python virtual environment
│
├── docs/                             # Additional documentation
│
├── GUIDE.md                          # This file
├── README.md                         # Project overview
├── STATUS.md                         # Current status & testing
├── DUAL-MODE.md                      # Dual-mode documentation
├── DUAL-MODE-SUMMARY.md             # Implementation summary
└── GUI-MODE-SUCCESS.md              # GUI mode implementation details
```

---

## Database Schema

**Location:** `~/chrome-pool-manager/pool-service/chrome_pool.db`

**Table: instances**
```sql
CREATE TABLE instances (
    instance_id TEXT PRIMARY KEY,      -- e.g., "chrome-9222"
    port INTEGER UNIQUE,               -- 9222-9232
    pid INTEGER,                       -- Chrome process ID
    status TEXT,                       -- idle, allocated, crashed
    mode TEXT,                         -- headless, gui
    agent_id TEXT,                     -- Agent that allocated this
    allocated_at TEXT,                 -- ISO timestamp
    expires_at TEXT,                   -- ISO timestamp
    last_heartbeat TEXT,               -- ISO timestamp
    tunnel_pid INTEGER                 -- SSH tunnel PID (GUI mode)
)
```

---

## Implementation Details

### Headless Mode Implementation

```python
# Start Chrome on WSL
args = [
    "/usr/bin/google-chrome",
    f"--remote-debugging-port={port}",
    f"--user-data-dir={user_data_dir}",
    "--headless=new",
    "--disable-extensions",
    "--no-sandbox",
    url
]
subprocess.Popen(args)
```

### GUI Mode Implementation

**Key Innovation: Windows Scheduled Tasks**

The challenge: SSH runs in non-interactive session (Session 0), but Chrome GUI requires interactive session (Session 1).

**Solution:** Use Windows Scheduled Tasks, which run in user's interactive session.

```python
# 1. Write PowerShell script locally
ps_script = f"""
Get-Process chrome -ErrorAction SilentlyContinue |
  Where-Object {{$_.CommandLine -like "*--remote-debugging-port={port}*"}} |
  Stop-Process -Force
Start-Process 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
  -ArgumentList '--remote-debugging-port={port}',
                '--user-data-dir={user_data_dir}',
                '--no-first-run',
                '{url}'
"""

# 2. Copy to Windows via SCP
with open(local_script, 'w') as f:
    f.write(ps_script)
subprocess.run(["scp", local_script, f"{windows_host}:{windows_script}"])

# 3. Create scheduled task
subprocess.run([
    "ssh", windows_host, "schtasks", "/Create", "/TN", task_name,
    "/TR", f'"powershell -ExecutionPolicy Bypass -File {windows_script}"',
    "/SC", "ONCE", "/ST", "00:00", "/F"
])

# 4. Run task immediately (runs in interactive session!)
subprocess.run(["ssh", windows_host, "schtasks", "/Run", "/TN", task_name])

# 5. Create SSH tunnel
subprocess.Popen([
    "ssh", "-f", "-N", "-L", f"{port}:127.0.0.1:{port}", windows_host
])

# 6. Verify Chrome is listening
verify_cmd = subprocess.run([
    "ssh", windows_host, "powershell", "-Command",
    f'"netstat -an | Select-String \\\":{port} \\\" | Select-String \\\"LISTENING\\\""'
])
```

**Cleanup:**
```python
# 1. Kill SSH tunnel
psutil.Process(tunnel_pid).kill()

# 2. Delete scheduled task
subprocess.run(["ssh", windows_host, "schtasks", "/Delete", "/TN", task_name, "/F"])

# 3. Stop Chrome by command line pattern
kill_cmd = f"Get-Process chrome | Where-Object {{$_.CommandLine -like '*--remote-debugging-port={port}*'}} | Stop-Process -Force"
subprocess.run(["ssh", windows_host, "powershell", "-Command", kill_cmd])
```

---

## Performance Characteristics

| Metric | Headless Mode | GUI Mode |
|--------|---------------|----------|
| Startup Time | 2-3 seconds | 6-8 seconds |
| Memory Usage | 150 MB | 200 MB |
| CPU Usage | Low | Medium |
| Network Latency | 0 ms | ~5 ms (SSH tunnel) |
| Best For | Automation, testing | Demos, debugging |

---

## Security Considerations

1. **Port Isolation**: Each instance uses unique port (9222-9232)
2. **Agent Isolation**: Each instance bound to specific agent_id
3. **Auto-Expiration**: Instances expire after timeout (default 300s)
4. **Local Only**: Debug ports only accessible on localhost
5. **SSH Keys**: GUI mode requires SSH key authentication (no passwords)
6. **No Exposed Ports**: Windows Chrome ports only accessible via SSH tunnel

---

## Common Use Cases

### Use Case 1: Automated Testing
```
Mode: Headless
Agents: Multiple test agents running in parallel
Benefit: Fast, no GUI overhead, 11 concurrent tests
```

### Use Case 2: Interactive Tutorial
```
Mode: GUI
Agents: Single agent demonstrating features
Benefit: User sees agent's actions in real-time
```

### Use Case 3: Screenshot Generation
```
Mode: Headless (fast) or GUI (for visual verification)
Agents: Content generation agents
Benefit: Quick screenshots without GUI overhead
```

### Use Case 4: Live Demonstration
```
Mode: GUI
Agents: Demo agent + presenter
Benefit: Both agent and presenter control same browser
```

---

## FAQ

**Q: Can I run headless and GUI instances simultaneously?**
A: Yes! The pool supports both modes concurrently. Each instance tracks its mode independently.

**Q: What happens if an agent crashes?**
A: Instances auto-expire after timeout (default 300s). The cleanup task runs every 30s and releases expired instances.

**Q: Can multiple agents share one instance?**
A: No. Each instance is allocated to a single agent_id. This ensures isolation and prevents conflicts.

**Q: How do I extend an instance's lifetime?**
A: Use the `send_heartbeat` MCP tool or POST to `/instance/{id}/heartbeat`. Each heartbeat extends the expiration time.

**Q: What if all 11 instances are allocated?**
A: New requests will fail with "No available Chrome instances". Release unused instances or wait for auto-expiration.

**Q: Can I change the port range?**
A: Yes. Edit `PORT_RANGE` in `chrome_pool_service.py` and restart the service. Update the database or delete it to reinitialize.

**Q: Why Windows Scheduled Tasks instead of direct SSH Start-Process?**
A: SSH runs in Session 0 (non-interactive), but Chrome GUI requires Session 1 (interactive). Scheduled Tasks run in the user's interactive session.

**Q: How do I clean up stuck instances?**
A: Restart the pool service: `systemctl --user restart chrome-pool`. This cleanly shuts down all instances and reinitializes the pool.

---

## Version History

**v1.0.0** (2026-01-19)
- ✅ Initial release
- ✅ Headless mode support
- ✅ GUI mode support with Windows Scheduled Tasks
- ✅ 11-instance pool (ports 9222-9232)
- ✅ MCP integration with 6 tools
- ✅ Auto-cleanup and expiration
- ✅ SQLite state persistence
- ✅ Systemd service integration

---

## Support & Maintenance

### Logs
```bash
# Pool service logs
journalctl --user -u chrome-pool -f

# Check instance status
curl http://localhost:8765/instances | jq
```

### Cleanup
```bash
# Kill all Chrome instances
pkill -f "chrome.*--remote-debugging-port"

# Kill all SSH tunnels
pkill -f "ssh.*-L.*922"

# Delete all scheduled tasks
ssh stark-windows 'schtasks /Query /TN ChromePool* /FO LIST | Select-String "TaskName:"' | while read line; do task=$(echo $line | awk '{print $2}'); ssh stark-windows "schtasks /Delete /TN $task /F"; done

# Reset database
systemctl --user stop chrome-pool
rm ~/chrome-pool-manager/pool-service/chrome_pool.db
systemctl --user start chrome-pool
```

---

## Credits

Built to solve the Chrome port conflict issue when multiple AI agents need simultaneous Chrome access. Enables collaborative development where human and AI can both see and interact with the same browser instance.

**Key Technologies:**
- FastAPI (HTTP server)
- MCP Python SDK 1.25.0 (MCP integration)
- SQLite (state persistence)
- systemd (service management)
- Windows Scheduled Tasks (GUI mode)
- SSH tunneling (remote debug access)

---

## Quick Reference Card

```bash
# Start pool service
systemctl --user start chrome-pool

# Allocate headless instance
curl -X POST http://localhost:8765/instance/allocate \
  -d '{"agent_id":"test"}' -H "Content-Type: application/json"

# Allocate GUI instance
curl -X POST http://localhost:8765/instance/allocate \
  -d '{"agent_id":"demo","mode":"gui","url":"http://google.com"}' \
  -H "Content-Type: application/json"

# Check instance
curl http://localhost:9222/json/version

# Release instance
curl -X POST http://localhost:8765/instance/chrome-9222/release

# View logs
journalctl --user -u chrome-pool -f

# List all instances
curl http://localhost:8765/instances | jq
```

---

**End of Guide** | Last Updated: 2026-01-19
