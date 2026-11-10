import os
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from worker.agent import app as worker_app, SOCKET_DIR, ACTIVE_VMS, reconciler_worker

WORKER_HEADERS = {"X-Worker-Token": "default-worker-secret"}

@pytest.mark.anyio
async def test_reconciler_cleans_stray_socket():
    # 1. Create an orphaned unmanaged socket file directly on disk
    stray_socket = os.path.join(SOCKET_DIR, "stray_orphan_test.sock")
    with open(stray_socket, "w") as f:
        f.write("")
    assert os.path.exists(stray_socket)

    # 2. Run one reconciliation cycle
    task = asyncio.create_task(reconciler_worker())
    await asyncio.sleep(0.5)
    task.cancel()

    # 3. Assert reconciler purged the orphaned socket
    assert not os.path.exists(stray_socket)

@pytest.mark.anyio
async def test_full_lifecycle_leaves_zero_sockets():
    transport = ASGITransport(app=worker_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Spawn VM
        payload = {
            "vm_id": "audit-vm-01",
            "name": "audit-guest",
            "vcpus": 1,
            "memory_mb": 512
        }
        spawn_res = await client.post("/api/v1/vms/spawn", json=payload, headers=WORKER_HEADERS)
        assert spawn_res.status_code == 201

        # Delete VM
        del_res = await client.delete("/api/v1/vms/audit-vm-01", headers=WORKER_HEADERS)
        assert del_res.status_code == 200

        # Verify socket file was purged from disk
        sock_path = os.path.join(SOCKET_DIR, "audit-vm-01.sock")
        assert not os.path.exists(sock_path)
