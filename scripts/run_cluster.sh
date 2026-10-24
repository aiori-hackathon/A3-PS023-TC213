#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "[+] Starting Two-Node VM Controller Cluster..."

# Ensure clean state
rm -f controller.db
mkdir -p /tmp/ch_sockets

# 1. Start Controller on port 8000
echo "[*] Launching Central Controller on port 8000..."
uvicorn controller.server:app --host 0.0.0.0 --port 8000 --log-level warning &
CONTROLLER_PID=$!

# Wait for Controller API
sleep 1

# 2. Start Worker Node 1 on port 8001
echo "[*] Launching Worker Agent 1 on port 8001 (Node ID: node-1)..."
NODE_ID="node-1" NODE_HOST="127.0.0.1" NODE_PORT=8001 CONTROLLER_URL="http://127.0.0.1:8000" \
    uvicorn worker.agent:app --host 0.0.0.0 --port 8001 --log-level warning &
WORKER1_PID=$!

# 3. Start Worker Node 2 on port 8002
echo "[*] Launching Worker Agent 2 on port 8002 (Node ID: node-2)..."
NODE_ID="node-2" NODE_HOST="127.0.0.1" NODE_PORT=8002 CONTROLLER_URL="http://127.0.0.1:8000" \
    uvicorn worker.agent:app --host 0.0.0.0 --port 8002 --log-level warning &
WORKER2_PID=$!

cleanup() {
    echo ""
    echo "[!] Shutting down cluster services..."
    kill "$CONTROLLER_PID" "$WORKER1_PID" "$WORKER2_PID" 2>/dev/null || true
    wait "$CONTROLLER_PID" "$WORKER1_PID" "$WORKER2_PID" 2>/dev/null || true
    echo "[+] Done."
}

trap cleanup INT TERM EXIT

echo ""
echo "=== Cluster Active ==="
echo "Controller: http://127.0.0.1:8000/docs"
echo "Worker 1:   http://127.0.0.1:8001/docs"
echo "Worker 2:   http://127.0.0.1:8002/docs"
echo "Press Ctrl+C to stop all cluster instances."
echo "======================="

wait