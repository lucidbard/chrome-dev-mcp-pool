"""
Chrome Manager MCP Server
Provides MCP tools for managing Chrome instances via the pool service.
"""
import asyncio
import json
import logging
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Configuration
POOL_SERVICE_URL = "http://localhost:8765"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MCP Server
app = Server("chrome-manager")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="request_chrome_instance",
            description="Request a Chrome instance from the pool. Returns instance details including debug port. Supports both headless (WSL) and GUI (Windows) modes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Unique identifier for the requesting agent"
                    },
                    "url": {
                        "type": "string",
                        "description": "Optional URL to load in Chrome (default: about:blank)",
                        "default": "about:blank"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Allocation timeout in seconds (default: 300)",
                        "default": 300
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["headless", "gui"],
                        "description": "Chrome mode: 'headless' for background (WSL), 'gui' for visible window (Windows). Default: headless",
                        "default": "headless"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="release_chrome_instance",
            description="Release a Chrome instance back to the pool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": "ID of the instance to release"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (for verification)"
                    }
                },
                "required": ["instance_id"]
            }
        ),
        Tool(
            name="get_instance_status",
            description="Get the status of a specific Chrome instance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": "ID of the instance to check"
                    }
                },
                "required": ["instance_id"]
            }
        ),
        Tool(
            name="list_chrome_instances",
            description="List all Chrome instances in the pool with their status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="stream_pool_status",
            description="Stream real-time updates of the Chrome pool status (HTTP streaming).",
            inputSchema={
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "integer",
                        "description": "How long to stream in seconds (default: 30)",
                        "default": 30
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="send_heartbeat",
            description="Send heartbeat to keep Chrome instance alive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": "ID of the instance"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID"
                    }
                },
                "required": ["instance_id", "agent_id"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""
    try:
        async with httpx.AsyncClient() as client:
            if name == "request_chrome_instance":
                agent_id = arguments["agent_id"]
                url = arguments.get("url", "about:blank")
                timeout = arguments.get("timeout", 300)
                mode = arguments.get("mode", "headless")

                response = await client.post(
                    f"{POOL_SERVICE_URL}/instance/allocate",
                    json={"agent_id": agent_id, "url": url, "timeout": timeout, "mode": mode},
                    timeout=10.0
                )

                if response.status_code == 200:
                    data = response.json()
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "instance_id": data["instance_id"],
                            "debug_port": data["debug_port"],
                            "debug_url": f"http://localhost:{data['debug_port']}",
                            "agent_id": data["agent_id"],
                            "expires_at": data["expires_at"],
                            "message": f"Chrome instance allocated on port {data['debug_port']}"
                        }, indent=2)
                    )]
                elif response.status_code == 503:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": "No available Chrome instances. All instances are currently allocated."
                        }, indent=2)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Failed to allocate instance: {response.text}"
                        }, indent=2)
                    )]

            elif name == "release_chrome_instance":
                instance_id = arguments["instance_id"]
                agent_id = arguments.get("agent_id")

                params = {"agent_id": agent_id} if agent_id else {}
                response = await client.post(
                    f"{POOL_SERVICE_URL}/instance/{instance_id}/release",
                    params=params,
                    timeout=10.0
                )

                if response.status_code == 200:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "instance_id": instance_id,
                            "message": f"Instance {instance_id} released successfully"
                        }, indent=2)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Failed to release instance: {response.text}"
                        }, indent=2)
                    )]

            elif name == "get_instance_status":
                instance_id = arguments["instance_id"]

                response = await client.get(
                    f"{POOL_SERVICE_URL}/instance/{instance_id}/status",
                    timeout=5.0
                )

                if response.status_code == 200:
                    data = response.json()
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            **data
                        }, indent=2)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Instance not found: {response.text}"
                        }, indent=2)
                    )]

            elif name == "list_chrome_instances":
                response = await client.get(
                    f"{POOL_SERVICE_URL}/instances",
                    timeout=5.0
                )

                if response.status_code == 200:
                    instances = response.json()
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "total": len(instances),
                            "instances": instances
                        }, indent=2)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Failed to list instances: {response.text}"
                        }, indent=2)
                    )]

            elif name == "stream_pool_status":
                duration = arguments.get("duration", 30)
                events = []

                async with client.stream(
                    "GET",
                    f"{POOL_SERVICE_URL}/stream",
                    timeout=None
                ) as response:
                    start_time = asyncio.get_event_loop().time()

                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                event = json.loads(line)
                                events.append(event)
                            except json.JSONDecodeError:
                                logger.error(f"Failed to parse event: {line}")

                        # Check duration
                        if asyncio.get_event_loop().time() - start_time > duration:
                            break

                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "events_received": len(events),
                        "duration": duration,
                        "events": events
                    }, indent=2)
                )]

            elif name == "send_heartbeat":
                instance_id = arguments["instance_id"]
                agent_id = arguments["agent_id"]

                response = await client.post(
                    f"{POOL_SERVICE_URL}/instance/{instance_id}/heartbeat",
                    params={"agent_id": agent_id},
                    timeout=5.0
                )

                if response.status_code == 200:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "message": "Heartbeat sent successfully"
                        }, indent=2)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Failed to send heartbeat: {response.text}"
                        }, indent=2)
                    )]

            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Unknown tool: {name}"
                    }, indent=2)
                )]

    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Failed to connect to pool service: {str(e)}",
                "hint": "Make sure the Chrome pool service is running on localhost:8765"
            }, indent=2)
        )]
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }, indent=2)
        )]


async def main():
    """Run MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
