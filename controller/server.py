import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
import httpx

from controller.models import (
    NodeHeartbeat,
    NodeRecord,
    VMCreateRequest,
    VMRecord,
)
from controller.store import MetadataStore
from controller.scheduler import (
    Scheduler,
    InsufficientCapacityError,
    NoHealthyNodesError,
)

app = FastAPI(title="TwoNodeVMController")

store = MetadataStore()
scheduler = Scheduler(store)

@app.post("/api/v1/nodes/heartbeat", status_code=status.HTTP_200_OK)
async def register_heartbeat(hb: NodeHeartbeat):
    store.upsert_node(hb)
    return {"status": "acknowledged", "node_id": hb.node_id}

@app.get("/api/v1/nodes", response_model=List[NodeRecord])
async def list_nodes():
    return store.list_nodes()

@app.post("/api/v1/vms", response_model=VMRecord, status_code=status.HTTP_201_CREATED)
async def create_vm(req: VMCreateRequest):
    # 1. Schedule node with atomic memory allocation
    try:
        selected_node = await scheduler.select_node(required_ram_mb=req.memory_mb)
    except (InsufficientCapacityError, NoHealthyNodesError) as err:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(err))

    vm_id = f"vm-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    vm_record = VMRecord(
        vm_id=vm_id,
        name=req.name,
        vcpus=req.vcpus,
        memory_mb=req.memory_mb,
        node_id=selected_node.node_id,
        status="PROVISIONING",
        created_at=now,
        updated_at=now,
    )
    store.insert_vm(vm_record)

    # 2. Invoke Worker node spawn endpoint
    worker_url = f"http://{selected_node.host}:{selected_node.port}/api/v1/vms/spawn"
    spawn_payload = {
        "vm_id": vm_id,
        "name": req.name,
        "vcpus": req.vcpus,
        "memory_mb": req.memory_mb,
        "kernel_path": req.kernel_path,
        "disk_path": req.disk_path,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(worker_url, json=spawn_payload)
            if resp.status_code != 201:
                store.update_vm_status(vm_id, "FAILED")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Worker node failed to spawn VM: {resp.text}",
                )
    except httpx.RequestError as exc:
        store.update_vm_status(vm_id, "FAILED")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to communicate with worker {selected_node.node_id}: {exc}",
        )

    store.update_vm_status(vm_id, "RUNNING")
    updated_vm = store.get_vm(vm_id)
    return updated_vm

@app.get("/api/v1/vms/{vm_id}", response_model=VMRecord)
async def get_vm_status(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    return vm

@app.delete("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK)
async def delete_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    if vm.node_id:
        nodes = {n.node_id: n for n in store.list_nodes()}
        node = nodes.get(vm.node_id)
        if node:
            worker_url = f"http://{node.host}:{node.port}/api/v1/vms/{vm_id}"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.delete(worker_url)
            except Exception:
                pass

    store.update_vm_status(vm_id, "TERMINATED")
    return {"vm_id": vm_id, "status": "TERMINATED"}