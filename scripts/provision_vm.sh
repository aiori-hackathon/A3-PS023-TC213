#!/usr/bin/env bash
set -euo pipefail

CONTROLLER_URL="${CONTROLLER_URL:-http://127.0.0.1:8000}"

echo "[*] Querying registered nodes in the cluster..."
curl -s "${CONTROLLER_URL}/api/v1/nodes" | python3 -m json.tool

echo ""
echo "[*] Submitting VM provisioning request (1 vCPU, 512MB RAM)..."
VM_RESP=$(curl -s -X POST "${CONTROLLER_URL}/api/v1/vms" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "demo-instance-01",
        "vcpus": 1,
        "memory_mb": 512
    }')

echo "$VM_RESP" | python3 -m json.tool

VM_ID=$(echo "$VM_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin).get('vm_id', ''))")

if [ -n "$VM_ID" ]; then
    echo ""
    echo "[*] Querying status for instance: $VM_ID"
    curl -s "${CONTROLLER_URL}/api/v1/vms/${VM_ID}" | python3 -m json.tool

    echo ""
    echo "[*] Cleaning up: Deleting instance $VM_ID"
    curl -s -X DELETE "${CONTROLLER_URL}/api/v1/vms/${VM_ID}" | python3 -m json.tool
fi