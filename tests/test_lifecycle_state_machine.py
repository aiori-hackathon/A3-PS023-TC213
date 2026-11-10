import pytest
from httpx import AsyncClient, ASGITransport
from worker.agent import app as worker_app

WORKER_HEADERS = {"X-Worker-Token": "default-worker-secret"}

@pytest.mark.anyio
async def test_vm_lifecycle_state_machine_and_conflicts():
    transport = ASGITransport(app=worker_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_payload = {
            "vm_id": "lifecycle-vm-01",
            "name": "state-test",
            "vcpus": 1,
            "memory_mb": 512
        }
        # 1. Create VM -> CREATED
        res = await client.post("/api/v1/vms/create", json=create_payload, headers=WORKER_HEADERS)
        assert res.status_code == 201
        assert res.json()["status"] == "CREATED"

        # 2. Duplicate create -> 409
        dup_res = await client.post("/api/v1/vms/create", json=create_payload, headers=WORKER_HEADERS)
        assert dup_res.status_code == 409

        # 3. Stop before start -> 409
        stop_err = await client.post("/api/v1/vms/lifecycle-vm-01/stop", headers=WORKER_HEADERS)
        assert stop_err.status_code == 409

        # 4. Start -> RUNNING
        start_res = await client.post("/api/v1/vms/lifecycle-vm-01/start", headers=WORKER_HEADERS)
        assert start_res.status_code == 200
        assert start_res.json()["status"] == "RUNNING"

        # 5. Double start -> 409
        start_err = await client.post("/api/v1/vms/lifecycle-vm-01/start", headers=WORKER_HEADERS)
        assert start_err.status_code == 409

        # 6. Stop -> STOPPED
        stop_res = await client.post("/api/v1/vms/lifecycle-vm-01/stop", headers=WORKER_HEADERS)
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "STOPPED"

        # 7. Double stop -> 409
        stop_err2 = await client.post("/api/v1/vms/lifecycle-vm-01/stop", headers=WORKER_HEADERS)
        assert stop_err2.status_code == 409

        # 8. Delete -> DELETED
        del_res = await client.delete("/api/v1/vms/lifecycle-vm-01", headers=WORKER_HEADERS)
        assert del_res.status_code == 200
        assert del_res.json()["state"] == "DELETED"
