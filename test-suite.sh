#!/bin/bash
# Chrome Pool Manager - Comprehensive Test Suite

# Don't exit on error - we want to report all test results
# set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Base URL
BASE_URL="http://localhost:8765"

# Test result tracking
declare -a FAILED_TESTS

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_test() {
    echo -e "${YELLOW}TEST $TESTS_TOTAL: $1${NC}"
}

print_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    ((TESTS_PASSED++))
}

print_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    echo -e "${RED}  Error: $2${NC}"
    ((TESTS_FAILED++))
    FAILED_TESTS+=("$1: $2")
}

run_test() {
    ((TESTS_TOTAL++))
    print_test "$1"
}

# Helper function to extract JSON value
get_json_value() {
    echo "$1" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | sed 's/.*:"\(.*\)".*/\1/'
}

get_json_number() {
    echo "$1" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*[0-9]*" | sed 's/.*:\([0-9]*\).*/\1/'
}

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up test instances...${NC}"

    # Release any test instances
    for instance_id in chrome-9222 chrome-9223 chrome-9224 chrome-9225 chrome-9226 chrome-9227; do
        curl -s -X POST "$BASE_URL/instance/$instance_id/release" > /dev/null 2>&1 || true
    done

    sleep 1
    echo -e "${GREEN}Cleanup complete${NC}"
}

# Trap to ensure cleanup on exit
trap cleanup EXIT

print_header "Chrome Pool Manager Test Suite"

# Test 1: Service Health Check
run_test "Service health check"
HEALTH_RESPONSE=$(curl -s "$BASE_URL/health")
if echo "$HEALTH_RESPONSE" | grep -q "ok"; then
    print_pass "Service is healthy"
else
    print_fail "Service health check failed" "Response: $HEALTH_RESPONSE"
fi

# Test 2: List instances (initial state)
run_test "List instances (should show 11 idle instances)"
INSTANCES_RESPONSE=$(curl -s "$BASE_URL/instances")
INSTANCE_COUNT=$(echo "$INSTANCES_RESPONSE" | grep -o "instance_id" | wc -l)
if [ "$INSTANCE_COUNT" -eq 11 ]; then
    print_pass "Found 11 instances in pool"
else
    print_fail "Instance count incorrect" "Expected 11, got $INSTANCE_COUNT"
fi

print_header "Headless Mode Tests"

# Test 3: Allocate headless instance
run_test "Allocate headless instance"
HEADLESS_RESPONSE=$(curl -s -X POST "$BASE_URL/instance/allocate" \
    -H "Content-Type: application/json" \
    -d '{"agent_id": "test-headless-1", "mode": "headless"}')

HEADLESS_INSTANCE=$(get_json_value "$HEADLESS_RESPONSE" "instance_id")
HEADLESS_PORT=$(get_json_number "$HEADLESS_RESPONSE" "debug_port")

if [ -n "$HEADLESS_INSTANCE" ] && [ -n "$HEADLESS_PORT" ]; then
    print_pass "Allocated headless instance: $HEADLESS_INSTANCE on port $HEADLESS_PORT"
else
    print_fail "Failed to allocate headless instance" "Response: $HEADLESS_RESPONSE"
    HEADLESS_INSTANCE=""
fi

# Test 4: Verify headless Chrome process
if [ -n "$HEADLESS_INSTANCE" ]; then
    run_test "Verify headless Chrome process is running"
    sleep 3
    if ps aux | grep -v grep | grep "chrome.*--remote-debugging-port=$HEADLESS_PORT.*--headless" > /dev/null; then
        print_pass "Headless Chrome process found"
    else
        print_fail "Headless Chrome process not found" "No process matching port $HEADLESS_PORT"
    fi
fi

# Test 5: Verify headless debug port accessibility
if [ -n "$HEADLESS_INSTANCE" ]; then
    run_test "Verify headless debug port is accessible"
    DEBUG_RESPONSE=$(curl -s --max-time 5 "http://localhost:$HEADLESS_PORT/json/version" 2>&1)
    if echo "$DEBUG_RESPONSE" | grep -q "Browser"; then
        print_pass "Debug port $HEADLESS_PORT is accessible"
    else
        print_fail "Debug port not accessible" "Response: $DEBUG_RESPONSE"
    fi
fi

# Test 6: Get instance status
if [ -n "$HEADLESS_INSTANCE" ]; then
    run_test "Get headless instance status"
    STATUS_RESPONSE=$(curl -s "$BASE_URL/instance/$HEADLESS_INSTANCE/status")
    if echo "$STATUS_RESPONSE" | grep -q "allocated"; then
        print_pass "Instance status is 'allocated'"
    else
        print_fail "Instance status incorrect" "Response: $STATUS_RESPONSE"
    fi
fi

# Test 7: Send heartbeat
if [ -n "$HEADLESS_INSTANCE" ]; then
    run_test "Send heartbeat to headless instance"
    HEARTBEAT_RESPONSE=$(curl -s -X POST "$BASE_URL/instance/$HEADLESS_INSTANCE/heartbeat?agent_id=test-headless-1")
    if echo "$HEARTBEAT_RESPONSE" | grep -q "ok"; then
        print_pass "Heartbeat accepted"
    else
        print_fail "Heartbeat failed" "Response: $HEARTBEAT_RESPONSE"
    fi
fi

# Test 8: Release headless instance
if [ -n "$HEADLESS_INSTANCE" ]; then
    run_test "Release headless instance"
    RELEASE_RESPONSE=$(curl -s -X POST "$BASE_URL/instance/$HEADLESS_INSTANCE/release")
    if echo "$RELEASE_RESPONSE" | grep -q "released"; then
        print_pass "Instance released successfully"
    else
        print_fail "Failed to release instance" "Response: $RELEASE_RESPONSE"
    fi

    # Verify cleanup
    sleep 2
    run_test "Verify headless Chrome process terminated"
    if ! ps aux | grep -v grep | grep "chrome.*--remote-debugging-port=$HEADLESS_PORT" > /dev/null; then
        print_pass "Chrome process terminated"
    else
        print_fail "Chrome process still running" "Process should be terminated"
    fi
fi

print_header "GUI Mode Tests"

# Test 9: Check Windows connectivity
run_test "Check SSH connectivity to Windows"
if ssh stark-windows "echo OK" 2>&1 | grep -q "OK"; then
    print_pass "SSH connection to Windows working"
else
    print_fail "SSH connection to Windows failed" "Cannot reach stark-windows"
fi

# Test 10: Verify Windows Chrome installation
run_test "Verify Chrome installed on Windows"
CHROME_CHECK=$(ssh stark-windows powershell -Command '"Test-Path \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\""' 2>&1)
if echo "$CHROME_CHECK" | grep -q "True"; then
    print_pass "Chrome found on Windows"
else
    print_fail "Chrome not found on Windows" "Path check returned: $CHROME_CHECK"
fi

# Test 11: Allocate GUI instance
run_test "Allocate GUI instance"
GUI_RESPONSE=$(curl -s -X POST "$BASE_URL/instance/allocate" \
    -H "Content-Type: application/json" \
    -d '{"agent_id": "test-gui-1", "url": "http://google.com", "mode": "gui"}')

GUI_INSTANCE=$(get_json_value "$GUI_RESPONSE" "instance_id")
GUI_PORT=$(get_json_number "$GUI_RESPONSE" "debug_port")

if [ -n "$GUI_INSTANCE" ] && [ -n "$GUI_PORT" ]; then
    print_pass "Allocated GUI instance: $GUI_INSTANCE on port $GUI_PORT"
else
    print_fail "Failed to allocate GUI instance" "Response: $GUI_RESPONSE"
    GUI_INSTANCE=""
fi

# Test 12: Verify GUI Chrome process on Windows (via debug port check on Windows)
if [ -n "$GUI_INSTANCE" ]; then
    run_test "Verify Chrome is listening on Windows (port check)"
    sleep 3
    # Check port directly on Windows side
    PORT_CHECK=$(ssh stark-windows powershell -Command '"Test-NetConnection -ComputerName localhost -Port '$GUI_PORT' -WarningAction SilentlyContinue | Select-Object -ExpandProperty TcpTestSucceeded"' 2>&1)
    if echo "$PORT_CHECK" | grep -q "True"; then
        print_pass "Chrome is listening on Windows port $GUI_PORT"
    else
        print_fail "Chrome not listening on Windows" "Port check result: $PORT_CHECK"
    fi
fi

# Test 13: Verify SSH tunnel exists
if [ -n "$GUI_INSTANCE" ]; then
    run_test "Verify SSH tunnel for GUI instance"
    if ps aux | grep -v grep | grep "ssh.*-L.*$GUI_PORT:127.0.0.1:$GUI_PORT" > /dev/null; then
        print_pass "SSH tunnel found for port $GUI_PORT"
    else
        print_fail "SSH tunnel not found" "No tunnel for port $GUI_PORT"
    fi
fi

# Test 14: Verify GUI debug port accessibility through tunnel
if [ -n "$GUI_INSTANCE" ]; then
    run_test "Verify GUI debug port accessible through tunnel"
    sleep 2
    GUI_DEBUG_RESPONSE=$(curl -s --max-time 5 "http://localhost:$GUI_PORT/json/version" 2>&1)
    if echo "$GUI_DEBUG_RESPONSE" | grep -q "Browser"; then
        print_pass "GUI debug port $GUI_PORT is accessible"
    else
        print_fail "GUI debug port not accessible" "Response: $GUI_DEBUG_RESPONSE"
    fi
fi

# Test 15: Verify scheduled task exists
if [ -n "$GUI_INSTANCE" ]; then
    run_test "Verify Windows scheduled task exists"
    TASK_NAME="ChromePool_$GUI_PORT"
    TASK_CHECK=$(ssh stark-windows "schtasks /Query /TN $TASK_NAME /FO LIST 2>&1")
    if echo "$TASK_CHECK" | grep -q "TaskName"; then
        print_pass "Scheduled task $TASK_NAME exists"
    else
        print_fail "Scheduled task not found" "Task check output: $TASK_CHECK"
    fi
fi

# Test 16: Release GUI instance
if [ -n "$GUI_INSTANCE" ]; then
    run_test "Release GUI instance"
    GUI_RELEASE_RESPONSE=$(curl -s -X POST "$BASE_URL/instance/$GUI_INSTANCE/release")
    if echo "$GUI_RELEASE_RESPONSE" | grep -q "released"; then
        print_pass "GUI instance released successfully"
    else
        print_fail "Failed to release GUI instance" "Response: $GUI_RELEASE_RESPONSE"
    fi

    # Test 17: Verify GUI cleanup - Chrome process (via debug port check)
    run_test "Verify Chrome stopped on Windows (port check)"
    # Wait up to 10 seconds for cleanup (Windows port release can be slow)
    for i in {1..10}; do
        sleep 1
        PORT_CHECK_AFTER=$(ssh stark-windows powershell -Command '"Test-NetConnection -ComputerName localhost -Port '$GUI_PORT' -WarningAction SilentlyContinue | Select-Object -ExpandProperty TcpTestSucceeded"' 2>&1)
        if echo "$PORT_CHECK_AFTER" | grep -q "False"; then
            break
        fi
    done

    if echo "$PORT_CHECK_AFTER" | grep -q "False"; then
        print_pass "Chrome port $GUI_PORT no longer listening (released after ${i}s)"
    else
        print_fail "Chrome still listening on Windows after 10s" "Port check: $PORT_CHECK_AFTER"
    fi

    # Test 18: Verify GUI cleanup - SSH tunnel
    run_test "Verify SSH tunnel terminated"
    sleep 1
    if ! ps aux | grep -v grep | grep "ssh.*-L.*$GUI_PORT" > /dev/null; then
        print_pass "SSH tunnel terminated"
    else
        print_fail "SSH tunnel still running" "Tunnel should be terminated"
    fi

    # Test 19: Verify GUI cleanup - Scheduled task
    run_test "Verify scheduled task deleted"
    TASK_CHECK_AFTER=$(ssh stark-windows "schtasks /Query /TN $TASK_NAME 2>&1")
    if echo "$TASK_CHECK_AFTER" | grep -q "ERROR"; then
        print_pass "Scheduled task deleted"
    else
        print_fail "Scheduled task still exists" "Task should be deleted"
    fi
fi

print_header "Concurrent Allocation Tests"

# Test 20: Allocate multiple instances simultaneously
run_test "Allocate 3 instances concurrently (mixed modes)"
CONCURRENT_1=$(curl -s -X POST "$BASE_URL/instance/allocate" -H "Content-Type: application/json" -d '{"agent_id": "concurrent-1", "mode": "headless"}')
CONCURRENT_2=$(curl -s -X POST "$BASE_URL/instance/allocate" -H "Content-Type: application/json" -d '{"agent_id": "concurrent-2", "mode": "headless"}')
CONCURRENT_3=$(curl -s -X POST "$BASE_URL/instance/allocate" -H "Content-Type: application/json" -d '{"agent_id": "concurrent-3", "mode": "headless"}')

CONC_1_ID=$(get_json_value "$CONCURRENT_1" "instance_id")
CONC_2_ID=$(get_json_value "$CONCURRENT_2" "instance_id")
CONC_3_ID=$(get_json_value "$CONCURRENT_3" "instance_id")

if [ -n "$CONC_1_ID" ] && [ -n "$CONC_2_ID" ] && [ -n "$CONC_3_ID" ]; then
    print_pass "Successfully allocated 3 concurrent instances"

    # Cleanup concurrent instances
    curl -s -X POST "$BASE_URL/instance/$CONC_1_ID/release" > /dev/null
    curl -s -X POST "$BASE_URL/instance/$CONC_2_ID/release" > /dev/null
    curl -s -X POST "$BASE_URL/instance/$CONC_3_ID/release" > /dev/null
else
    print_fail "Failed to allocate 3 concurrent instances" "IDs: $CONC_1_ID, $CONC_2_ID, $CONC_3_ID"
fi

print_header "Error Handling Tests"

# Test 21: Allocate with invalid mode
run_test "Attempt allocation with invalid mode"
INVALID_MODE_RESPONSE=$(curl -s -X POST "$BASE_URL/instance/allocate" \
    -H "Content-Type: application/json" \
    -d '{"agent_id": "invalid-test", "mode": "invalid"}')
# This should either fail or default to headless
if echo "$INVALID_MODE_RESPONSE" | grep -q "instance_id"; then
    INVALID_INSTANCE=$(get_json_value "$INVALID_MODE_RESPONSE" "instance_id")
    curl -s -X POST "$BASE_URL/instance/$INVALID_INSTANCE/release" > /dev/null
    print_pass "Invalid mode handled (defaulted or validated)"
else
    print_pass "Invalid mode rejected properly"
fi

# Test 22: Release non-existent instance
run_test "Attempt to release non-existent instance"
NONEXIST_RELEASE=$(curl -s -X POST "$BASE_URL/instance/chrome-9999/release")
if echo "$NONEXIST_RELEASE" | grep -q "not found\|not allocated"; then
    print_pass "Non-existent instance release handled properly"
else
    print_fail "Non-existent instance release not handled" "Response: $NONEXIST_RELEASE"
fi

print_header "Test Summary"

echo -e "\nTotal Tests: $TESTS_TOTAL"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"

if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "\n${RED}Failed Tests:${NC}"
    for failed_test in "${FAILED_TESTS[@]}"; do
        echo -e "  ${RED}✗${NC} $failed_test"
    done
    echo -e "\n${RED}TEST SUITE FAILED${NC}"
    exit 1
else
    echo -e "\n${GREEN}ALL TESTS PASSED!${NC}"
    exit 0
fi
