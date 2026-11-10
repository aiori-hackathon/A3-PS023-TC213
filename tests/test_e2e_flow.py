import pytest
from httpx import AsyncClient, ASGITransport
from controller.server import app as controller_app
from worker.agent import app as worker_app

CONTROLLER_HEADERS = {"Authorization": "Bearer default-admin-token"}
WORKER_HEADERS = {"X-Worker-Token": "default-worker-secret"}

@pytest.mark.anyio
async def test_end_to_end_orchestration_flow():
    c_transport = ASGITransport(app=controller_app)
    w_transport = ASGITransport(app=worker_app)

    async with AsyncClient(transport=c_transport, base_url="http://controller") as c_client, \
               AsyncClient(transport=w_transport, base_url="http://worker") as w_client:

        # 1. Register Worker Node 1
        hb1 = {
            "node_id": "node-1",
            "host": "worker",
            "port": 8001,
            "total_ram_mb": 4096,
            "free_ram_mb": 2048
        }
        res1 = await c_client.post("/api/v1/nodes/heartbeat", json=hb1)
        assert res1.status_code == 200

        # 2. Register Worker Node 2
        hb2 = {
            "node_id": "node-2",
            "host": "worker",
            "port": 8001,
            "total_ram_mb": 16384,
            "free_ram_mb": 8192
        }
        res2 = await c_client.post("/api/v1/nodes/heartbeat", json=hb2)
        assert res2.status_code == 200

        # 3. Query cluster nodes with auth
        nodes_res = await c_client.get("/api/v1/nodes", headers=CONTROLLER_HEADERS)
        assert nodes_res.status_code == 200
        assert len(nodes_res.json()) == 2

        # 4. Directly verify Worker spawn endpoint with auth
        spawn_req = {
            "vm_id": "e2e-vm-01",
            "name": "orchestrated-guest",
            "vcpus": 2,
            "memory_mb": 1024
        }
        spawn_res = await w_client.post("/api/v1/vms/spawn", json=spawn_req, headers=WORKER_HEADERS)
        assert spawn_res.status_code == 201

        # 5. Clean up VM on worker
        del_res = await w_client.delete("/api/v1/vms/e2e-vm-01", headers=WORKER_HEADERS)
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "TERMINATED"
