import pytest
from httpx import AsyncClient, ASGITransport
from controller.server import app as controller_app
from worker.agent import app as worker_app

CONTROLLER_HEADERS = {"Authorization": "Bearer default-admin-token"}
WORKER_HEADERS = {"X-Worker-Token": "default-worker-secret"}

@pytest.mark.anyio
async def test_controller_rejects_unauthenticated_requests():
    transport = ASGITransport(app=controller_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request without Bearer token must return 401
        res = await client.get("/api/v1/nodes")
        assert res.status_code == 401

        # Request with invalid token must return 401
        res_bad = await client.get("/api/v1/nodes", headers={"Authorization": "Bearer wrong-token"})
        assert res_bad.status_code == 401

@pytest.mark.anyio
async def test_worker_rejects_unauthorized_token():
    transport = ASGITransport(app=worker_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request without X-Worker-Token must return 401
        res = await client.get("/api/v1/vms")
        assert res.status_code == 401

        # Request with bad token must return 401
        res_bad = await client.get("/api/v1/vms", headers={"X-Worker-Token": "wrong-secret"})
        assert res_bad.status_code == 401

@pytest.mark.anyio
async def test_resource_limit_guardrails_enforced():
    transport = ASGITransport(app=controller_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Reject vCPU > 4
        bad_cpu = {
            "name": "over-limit-cpu",
            "vcpus": 8,
            "memory_mb": 512
        }
        res_cpu = await client.post("/api/v1/vms", json=bad_cpu, headers=CONTROLLER_HEADERS)
        assert res_cpu.status_code == 422

        # 2. Reject RAM > 2048 MB
        bad_ram = {
            "name": "over-limit-ram",
            "vcpus": 2,
            "memory_mb": 4096
        }
        res_ram = await client.post("/api/v1/vms", json=bad_ram, headers=CONTROLLER_HEADERS)
        assert res_ram.status_code == 422

        # 3. Reject RAM < 128 MB
        bad_low_ram = {
            "name": "under-limit-ram",
            "vcpus": 1,
            "memory_mb": 64
        }
        res_low = await client.post("/api/v1/vms", json=bad_low_ram, headers=CONTROLLER_HEADERS)
        assert res_low.status_code == 422
