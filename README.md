# Chrome Pool Manager

Manage a pool of Chrome instances with remote debugging for multi-agent development workflows.

**📖 [Complete Guide](GUIDE.md)** - Single-document reference for all features, usage, and troubleshooting

## Problem

When multiple AI agents (Claude Code, Cursor, etc.) need browser access simultaneously, conflicts arise:
- Port collisions on 9222
- Agents interfering with each other's work
- Manual Chrome instance management
- No isolation between agents

## Solution

**Chrome Pool Manager** provides:
- Pool of isolated Chrome instances (ports 9222-9232)
- **Dual-mode support:** Headless (WSL) or GUI (Windows)
- Automatic allocation and cleanup
- MCP tools for agent integration
- HTTP API for programmatic control
- System service that runs automatically

## Dual-Mode Support

**Headless Mode (WSL):**
- Fast startup, low resource usage
- Perfect for automated testing, CI/CD
- Chrome runs in background, no GUI

**GUI Mode (Windows):**
- Visible Chrome window on Windows desktop
- Great for demos, collaborative debugging
- User and agent can both interact with browser

See [DUAL-MODE.md](DUAL-MODE.md) for complete documentation.

## Architecture

```
┌─────────────────────────────────────────┐
│ Pool Service (FastAPI)                  │
│ - Manages Chrome instance pool          │
│ - Allocation & lifecycle management     │
│ - HTTP API on localhost:8765            │
│ - SQLite state persistence              │
└─────────────────────────────────────────┘
                 ↑
                 │ HTTP
                 │
┌─────────────────────────────────────────┐
│ MCP Server (stdio protocol)             │
│ - Exposes MCP tools to agents           │
│ - HTTP client to pool service           │
│ - Handles streaming & heartbeats        │
└─────────────────────────────────────────┘
                 ↑
                 │ MCP Protocol
                 │
┌─────────────────────────────────────────┐
│ AI Agents (Claude Code, etc.)           │
│ - Request Chrome via MCP tools          │
│ - Get isolated debug port               │
│ - Use chrome-devtools MCP               │
└─────────────────────────────────────────┘
```

## Installation

```bash
cd chrome-pool-manager
./install.sh
```

This will:
1. Check/install Chrome for WSL
2. Create Python virtual environments
3. Install dependencies
4. Set up systemd user services
5. Enable auto-start

## Usage

### Start Services

```bash
# Start pool service
systemctl --user start chrome-pool

# Start MCP server
systemctl --user start chrome-manager-mcp

# Both services will auto-start on login
```

### Check Status

```bash
# Service status
systemctl --user status chrome-pool
systemctl --user status chrome-manager-mcp

# View logs
journalctl --user -u chrome-pool -f
journalctl --user -u chrome-manager-mcp -f

# Test HTTP API
curl http://localhost:8765/health
curl http://localhost:8765/instances
```

### MCP Integration

Add to your `~/.config/claude-code/mcp_config.json`:

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

## MCP Tools

### `request_chrome_instance`

Request a Chrome instance from the pool.

**Parameters:**
- `agent_id` (required): Unique identifier for your agent
- `url` (optional): URL to load (default: "about:blank")
- `timeout` (optional): Allocation timeout in seconds (default: 300)
- `mode` (optional): "headless" (WSL, default) or "gui" (Windows visible)

**Returns:**
```json
{
  "success": true,
  "instance_id": "chrome-9222",
  "debug_port": 9222,
  "debug_url": "http://localhost:9222",
  "agent_id": "my-agent-123",
  "expires_at": "2026-01-19T10:30:00"
}
```

**Example usage:**
```javascript
// In your agent code
const result = await use_mcp_tool("chrome-manager", "request_chrome_instance", {
  agent_id: "my-agent-123",
  url: "http://192.168.1.86:3000"
});

// Use the debug port with chrome-devtools MCP
const debugPort = result.debug_port; // 9222
```

### `release_chrome_instance`

Release a Chrome instance back to the pool.

**Parameters:**
- `instance_id` (required): ID of instance to release
- `agent_id` (optional): Agent ID for verification

**Returns:**
```json
{
  "success": true,
  "instance_id": "chrome-9222",
  "message": "Instance chrome-9222 released successfully"
}
```

### `get_instance_status`

Get status of a specific instance.

**Parameters:**
- `instance_id` (required): ID of instance to check

**Returns:**
```json
{
  "success": true,
  "instance_id": "chrome-9222",
  "port": 9222,
  "pid": 12345,
  "status": "allocated",
  "agent_id": "my-agent-123",
  "allocated_at": "2026-01-19T10:25:00",
  "expires_at": "2026-01-19T10:30:00"
}
```

### `list_chrome_instances`

List all instances in the pool.

**Returns:**
```json
{
  "success": true,
  "total": 11,
  "instances": [...]
}
```

### `stream_pool_status`

Stream real-time pool status updates via HTTP streaming.

**Parameters:**
- `duration` (optional): How long to stream in seconds (default: 30)

**Returns:** Newline-delimited JSON events

### `send_heartbeat`

Keep your instance alive by sending heartbeat.

**Parameters:**
- `instance_id` (required): Your instance ID
- `agent_id` (required): Your agent ID

## HTTP API

### `POST /instance/allocate`

Allocate a Chrome instance.

```bash
curl -X POST http://localhost:8765/instance/allocate \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent-123",
    "url": "about:blank",
    "timeout": 300
  }'
```

### `POST /instance/{instance_id}/release`

Release an instance.

```bash
curl -X POST http://localhost:8765/instance/chrome-9222/release?agent_id=my-agent-123
```

### `GET /instance/{instance_id}/status`

Get instance status.

```bash
curl http://localhost:8765/instance/chrome-9222/status
```

### `GET /instances`

List all instances.

```bash
curl http://localhost:8765/instances
```

### `POST /instance/{instance_id}/heartbeat`

Send heartbeat.

```bash
curl -X POST http://localhost:8765/instance/chrome-9222/heartbeat?agent_id=my-agent-123
```

### `GET /stream`

Stream pool events (newline-delimited JSON).

```bash
curl http://localhost:8765/stream
```

## Configuration

Edit `pool-service/chrome_pool_service.py`:

```python
# Chrome binary path
CHROME_PATH = "/usr/bin/google-chrome"

# Port range for pool (11 instances: 9222-9232)
PORT_RANGE = range(9222, 9233)

# Idle timeout before auto-release
IDLE_TIMEOUT = 300  # 5 minutes
```

## Conflict Resolution

- **One instance per agent**: Each agent gets dedicated Chrome instance
- **Auto-cleanup**: Instances released after timeout or agent disconnect
- **Queue when full**: Returns 503 if all instances allocated
- **Force release**: Admin can manually release via API
- **Heartbeat mechanism**: Agents can extend allocation with heartbeats

## Troubleshooting

### Pool service won't start

```bash
# Check logs
journalctl --user -u chrome-pool -n 50

# Common issues:
# - Chrome not installed: run install.sh again
# - Port 8765 in use: change port in chrome_pool_service.py
# - Python env issues: recreate venv
```

### No available instances

```bash
# List all instances
curl http://localhost:8765/instances | jq

# Release stale instances
curl -X POST http://localhost:8765/instance/chrome-9222/release

# Restart pool service
systemctl --user restart chrome-pool
```

### MCP tools not working

```bash
# Check MCP server
systemctl --user status chrome-manager-mcp

# Test pool service
curl http://localhost:8765/health

# Verify MCP config
cat ~/.config/claude-code/mcp_config.json
```

### Chrome won't start

Chrome in WSL requires specific flags. The service uses:
- `--headless=new`: New headless mode
- `--no-sandbox`: Required for WSL
- `--disable-gpu`: Avoid GPU issues

## Development

```bash
# Run pool service manually
cd pool-service
source venv/bin/activate
python chrome_pool_service.py

# Run MCP server manually
cd mcp-server
source venv/bin/activate
python chrome_manager_mcp.py

# Test with curl
curl http://localhost:8765/health
```

## License

MIT

## Contributing

This is a utility tool for AI-augmented development. Contributions welcome!

Key areas:
- Additional allocation strategies
- Enhanced monitoring/metrics
- Windows native support
- Docker containerization
