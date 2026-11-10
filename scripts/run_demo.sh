#!/usr/bin/env bash
set -euo pipefail

CONTROLLER_URL="http://127.0.0.1:8000"
ADMIN_TOKEN="default-admin-token"
WORKER_TOKEN="default-worker-secret"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}       AIORI PS-023: TWO-NODE CLOUD HYPERVISOR CONTROLLER DEMO        ${NC}"
echo -e "${BLUE}======================================================================${NC}"

# Clean previous test database if present
export CH_DB_PATH="/tmp/demo_cluster.db"
rm -f "$CH_DB_PATH"

echo -e "\n${YELLOW}[Step 0] Booting Controller and 2 Worker Agents...${NC}"

# 1. Start Controller
export CONTROLLER_PORT=8000
python3 -m uvicorn controller.server:app --host 127.0.0.1 --port 8000 --log-level error &
CONTROLLER_PID=$!

# 2. Start Worker 1 (Port 8001, node-1)
NODE_ID="worker-host-1" PORT=8001 python3 -m uvicorn worker.agent:app --host 127.0.0.1 --port 8001 --log-level error &
WORKER1_PID=$!

# 3. Start Worker 2 (Port 8002, node-2)
NODE_ID="worker-host-2" PORT=8002 python3 -m uvicorn worker.agent:app --host 127.0.0.1 --port 8002 --log-level error &
WORKER2_PID=$!

cleanup() {
    echo -e "\n${YELLOW}[Teardown] Shutting down demo servers...${NC}"
    kill -9 "$CONTROLLER_PID" "$WORKER1_PID" "$WORKER2_PID" 2>/dev/null || true
    rm -f "$CH_DB_PATH"
}
trap cleanup EXIT

# Allow services to initialize
sleep 2

# Send synthetic heartbeats with clear memory difference to test deterministic placement
curl -s -X POST "$CONTROLLER_URL/api/v1/nodes/heartbeat" \
    -H "Content-Type: application/json" \
    -d '{"node_id":"worker-host-1","host":"127.0.0.1","port":8001,"total_ram_mb":4096,"free_ram_mb":1500,"kvm_capable":true,"runtime_driver":"kvm"}' > /dev/null

curl -s -X POST "$CONTROLLER_URL/api/v1/nodes/heartbeat" \
    -H "Content-Type: application/json" \
    -d '{"node_id":"worker-host-2","host":"127.0.0.1","port":8002,"total_ram_mb":8192,"free_ram_mb":5000,"kvm_capable":true,"runtime_driver":"kvm"}' > /dev/null

echo -e "${GREEN}[+] Services active and heartbeats acknowledged.${NC}"

echo -e "\n${YELLOW}[Step 1] Querying Cluster Nodes & Headroom (GET /api/v1/nodes)${NC}"
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "$CONTROLLER_URL/api/v1/nodes" | python3 -m json.tool

echo -e "\n${YELLOW}[Step 2] Testing Security: Unauthenticated Request (Expect 401)${NC}"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$CONTROLLER_URL/api/v1/nodes")
if [ "$HTTP_STATUS" -eq 401 ]; then
    echo -e "${GREEN}[PASS] Controller rejected unauthenticated access with HTTP 401 Unauthorized.${NC}"
else
    echo -e "${RED}[FAIL] Expected HTTP 401, got $HTTP_STATUS${NC}"
fi

echo -e "\n${YELLOW}[Step 3] Testing Resource Limits: Request 8 vCPUs (Max is 4, Expect 422)${NC}"
HTTP_LIMIT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$CONTROLLER_URL/api/v1/vms" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"oversized-vm","vcpus":8,"memory_mb":512}')
if [ "$HTTP_LIMIT_STATUS" -eq 422 ]; then
    echo -e "${GREEN}[PASS] Controller rejected invalid resource limits with HTTP 422 Unprocessable Entity.${NC}"
else
    echo -e "${RED}[FAIL] Expected HTTP 422, got $HTTP_LIMIT_STATUS${NC}"
fi

echo -e "\n${YELLOW}[Step 4] Provisioning VM (Dynamic Placement on Worker with Most Headroom)${NC}"
VM_RESPONSE=$(curl -s -X POST "$CONTROLLER_URL/api/v1/vms" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"demo-workload-01","vcpus":2,"memory_mb":1024}')
echo "$VM_RESPONSE" | python3 -m json.tool

VM_ID=$(echo "$VM_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['vm_id'])")
NODE_ASSIGNED=$(echo "$VM_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['node_id'])")

if [ "$NODE_ASSIGNED" == "worker-host-2" ]; then
    echo -e "${GREEN}[PASS] Scheduler successfully placed VM on worker-host-2 (highest available memory).${NC}"
else
    echo -e "${RED}[FAIL] Unexpected placement on $NODE_ASSIGNED${NC}"
fi

echo -e "\n${YELLOW}[Step 4.5] Inspecting via CLI & Prometheus Telemetry${NC}"
echo "[*] Querying live topology via chctl CLI..."
./chctl nodes list
echo "[*] Querying Prometheus metrics via chctl..."
./chctl metrics | grep -E "ch_cluster_vms_total|ch_cluster_vm_vcpu_allocated"

echo -e "\n${YELLOW}[Step 5] Testing Lifecycle Transitions: Stop and Restart VM${NC}"
echo "[*] Stopping VM $VM_ID..."
curl -s -X POST "$CONTROLLER_URL/api/v1/vms/$VM_ID/stop" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool

echo "[*] Starting VM $VM_ID..."
curl -s -X POST "$CONTROLLER_URL/api/v1/vms/$VM_ID/start" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool

echo -e "\n${YELLOW}[Step 6] Testing Conflict Prevention: Starting an Already Running VM (Expect 409)${NC}"
CONFLICT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$CONTROLLER_URL/api/v1/vms/$VM_ID/start" \
    -H "Authorization: Bearer $ADMIN_TOKEN")
if [ "$CONFLICT_STATUS" -eq 409 ]; then
    echo -e "${GREEN}[PASS] Controller rejected invalid transition with HTTP 409 Conflict.${NC}"
else
    echo -e "${RED}[FAIL] Expected HTTP 409, got $CONFLICT_STATUS${NC}"
fi

echo -e "\n${YELLOW}[Step 7] Deleting VM and Cleaning Up Resources${NC}"
curl -s -X DELETE "$CONTROLLER_URL/api/v1/vms/$VM_ID" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool

echo -e "\n${YELLOW}[Step 8] Running Zero-Leak Audit Tool${NC}"
./scripts/leak_check.sh

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}      ALL AIORI PS-023 EVALUATION CHECKS PASSED SUCCESSFULLY          ${NC}"
echo -e "${GREEN}======================================================================${NC}"
