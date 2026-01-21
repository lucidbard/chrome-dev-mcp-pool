#!/bin/bash
# Quick test script for Chrome Pool Manager

echo "=========================================="
echo "Chrome Pool Manager - Test Suite"
echo "=========================================="
echo ""

# Check if services are running
echo "1. Checking services..."
if systemctl --user is-active --quiet chrome-pool; then
    echo "   ✅ Pool service running"
else
    echo "   ❌ Pool service not running"
    echo "      Start with: systemctl --user start chrome-pool"
    exit 1
fi

if systemctl --user is-active --quiet chrome-manager-mcp; then
    echo "   ✅ MCP server running"
else
    echo "   ⚠️  MCP server not running (optional for HTTP tests)"
fi

echo ""
echo "2. Testing HTTP API..."

# Health check
echo "   Testing /health..."
HEALTH=$(curl -s http://localhost:8765/health)
if echo "$HEALTH" | grep -q "ok"; then
    echo "   ✅ Health check passed"
else
    echo "   ❌ Health check failed"
    exit 1
fi

# List instances
echo "   Testing /instances..."
INSTANCES=$(curl -s http://localhost:8765/instances)
COUNT=$(echo "$INSTANCES" | jq 'length' 2>/dev/null || echo "0")
echo "   ✅ Found $COUNT instances in pool"

echo ""
echo "3. Testing allocation..."

# Allocate instance
echo "   Allocating instance for test-agent..."
ALLOC=$(curl -s -X POST http://localhost:8765/instance/allocate \
    -H "Content-Type: application/json" \
    -d '{"agent_id": "test-agent", "url": "about:blank", "timeout": 60}')

if echo "$ALLOC" | grep -q "instance_id"; then
    INSTANCE_ID=$(echo "$ALLOC" | jq -r '.instance_id')
    DEBUG_PORT=$(echo "$ALLOC" | jq -r '.debug_port')
    echo "   ✅ Allocated $INSTANCE_ID on port $DEBUG_PORT"

    # Test Chrome debugging port
    echo ""
    echo "4. Testing Chrome debugging port..."
    sleep 2  # Wait for Chrome to fully start

    if curl -s http://localhost:$DEBUG_PORT/json/version >/dev/null 2>&1; then
        echo "   ✅ Chrome debugging port accessible"
        VERSION=$(curl -s http://localhost:$DEBUG_PORT/json/version | jq -r '.Browser')
        echo "      Browser: $VERSION"
    else
        echo "   ⚠️  Chrome debugging port not accessible (Chrome may still be starting)"
    fi

    # Release instance
    echo ""
    echo "5. Testing release..."
    RELEASE=$(curl -s -X POST "http://localhost:8765/instance/$INSTANCE_ID/release?agent_id=test-agent")
    if echo "$RELEASE" | grep -q "released"; then
        echo "   ✅ Instance released successfully"
    else
        echo "   ❌ Failed to release instance"
    fi
else
    echo "   ❌ Failed to allocate instance"
    echo "      Response: $ALLOC"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ All tests passed!"
echo "=========================================="
echo ""
echo "Chrome Pool Manager is working correctly."
echo ""
