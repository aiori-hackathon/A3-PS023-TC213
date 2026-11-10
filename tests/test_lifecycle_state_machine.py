import pytest
from httpx import AsyncClient, ASGITransport
from worker.agent import app as worker_app

@pytest.mark.anyio
async def test_vm_lifecycle_state_machine_and_conflicts():
    transport = ASGITransport(app=worker_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create VM -> transitions to CREATED
        create_payload = {
            "vm_id": "lifecycle-vm-01",
            "name": "state-test",
            "vcpus": 1,
            "memory_mb": 512
        }
        res = await client.post("/api/v1/vms/create", json=create_payload)
        assert res.status_code == 201
        assert res.json()["status"] == "CREATED"

        # 2. Duplicate create must return 409 Conflict
        dup_res = await client.post("/api/v1/vms/create", json=create_payload)
        assert dup_res.status_code == 409

        # 3. Stopping a CREATED VM (not yet running) must return 409 Conflict
        stop_err = await client.post("/api/v1/vms/lifecycle-vm-01/stop")
        assert stop_err.status_code == 409

        # 4. Start VM -> transitions to RUNNING
        start_res = await client.post("/api/v1/vms/lifecycle-vm-01/start")
        assert start_res.status_code == 200
        assert start_res.json()["status"] == "RUNNING"

        # 5. Starting an already RUNNING VM must return 409 Conflict
        start_err = await client.post("/api/v1/vms/lifecycle-vm-01/start")
        assert start_err.status_code == 409

        # 6. Stop VM -> transitions to STOPPED
        stop_res = await client.post("/api/v1/vms/lifecycle-vm-01/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "STOPPED"

        # 7. Stopping an already STOPPED VM must return 409 Conflict
        stop_err2 = await client.post("/api/v1/vms/lifecycle-vm-01/stop")
        assert stop_err2.status_code == 409

        # 8. Terminate VM -> transitions to DELETED
        del_res = await client.delete("/api/v1/vms/lifecycle-vm-01")
        assert del_res.status_code == 200
        assert del_res.json()["state"] == "DELETED"