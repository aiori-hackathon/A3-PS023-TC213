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

def test_artifact_resolution_pipeline():
    from worker.agent import resolve_and_validate_artifacts
    import os

    # 1. Verify default fallback generation
    kernel, disk = resolve_and_validate_artifacts()
    assert kernel.endswith("vmlinux.bin")
    assert disk.endswith("rootfs.raw")
    assert os.path.exists(kernel)
    assert os.path.exists(disk)

    # 2. Verify custom overrides
    custom_k = "/tmp/custom_vmlinux.bin"
    custom_d = "/tmp/custom_rootfs.raw"
    k_out, d_out = resolve_and_validate_artifacts(kernel_path=custom_k, disk_path=custom_d)
    assert k_out == custom_k
    assert d_out == custom_d
    assert os.path.exists(custom_k)
    assert os.path.exists(custom_d)