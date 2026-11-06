#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "=========================================================="
echo " Starting Cloud Hypervisor Distributed Orchestrator Cluster"
echo "=========================================================="

cleanup() {
    echo -e "\nShutting down cluster nodes..."
    kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[1/3] Booting Controller on :8000..."
uvicorn controller.server:app --host 0.0.0.0 --port 8000 --log-level warning &
sleep 2

echo "[2/3] Booting Worker Node 1 on :8001..."
NODE_ID=node-1 NODE_PORT=8001 CONTROLLER_URL=http://127.0.0.1:8000 \
  uvicorn worker.agent:app --host 0.0.0.0 --port 8001 --log-level warning &

echo "[3/3] Booting Worker Node 2 on :8002..."
NODE_ID=node-2 NODE_PORT=8002 CONTROLLER_URL=http://127.0.0.1:8000 \
  uvicorn worker.agent:app --host 0.0.0.0 --port 8002 --log-level warning &

echo "=========================================================="
echo " Cluster Online!"
echo " Console Dashboard : http://127.0.0.1:8000/dashboard"
echo " Interactive OpenAPI: http://127.0.0.1:8000/docs"
echo " Press Ctrl+C to terminate all services."
echo "=========================================================="

wait
