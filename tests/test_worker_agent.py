import pytest
from httpx import AsyncClient, ASGITransport
from worker.agent import app, ACTIVE_VMS

@pytest.mark.anyio
async def test_worker_spawn_and_terminate():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Spawn VM
        payload = {
            "vm_id": "test-vm-100",
            "name": "integration-vm",
            "vcpus": 1,
            "memory_mb": 512
        }
        res = await client.post("/api/v1/vms/spawn", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["vm_id"] == "test-vm-100"
        assert data["status"] == "RUNNING"
        assert "test-vm-100" in ACTIVE_VMS

        # 2. Terminate VM
        del_res = await client.delete("/api/v1/vms/test-vm-100")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "TERMINATED"
        assert "test-vm-100" not in ACTIVE_VMS