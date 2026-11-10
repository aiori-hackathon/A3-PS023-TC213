import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
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

@app.post("/api/v1/vms/{vm_id}/start", status_code=status.HTTP_200_OK)
async def start_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found.")

    if vm.status == "RUNNING":
        raise HTTPException(status_code=409, detail=f"VM {vm_id} is already RUNNING.")
    if vm.status not in ("CREATED", "STOPPED"):
        raise HTTPException(status_code=409, detail=f"Cannot start VM from state {vm.status}.")

    node = store.get_node(vm.node_id) if vm.node_id else None
    if not node:
        raise HTTPException(status_code=502, detail="Assigned worker node unavailable.")

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"http://{node.host}:{node.port}/api/v1/vms/{vm_id}/start")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to communicate with worker: {e}")

    store.update_vm_status(vm_id, "RUNNING")
    return {"vm_id": vm_id, "status": "RUNNING"}

@app.post("/api/v1/vms/{vm_id}/stop", status_code=status.HTTP_200_OK)
async def stop_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found.")

    if vm.status == "STOPPED":
        raise HTTPException(status_code=409, detail=f"VM {vm_id} is already STOPPED.")
    if vm.status != "RUNNING":
        raise HTTPException(status_code=409, detail=f"Cannot stop VM from state {vm.status}.")

    node = store.get_node(vm.node_id) if vm.node_id else None
    if not node:
        raise HTTPException(status_code=502, detail="Assigned worker node unavailable.")

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"http://{node.host}:{node.port}/api/v1/vms/{vm_id}/stop")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to communicate with worker: {e}")

    store.update_vm_status(vm_id, "STOPPED")
    return {"vm_id": vm_id, "status": "STOPPED"}

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

@app.get("/api/v1/vms")
async def list_vms():
    """Returns all tracked microVMs from the metadata store."""
    if hasattr(store, "list_vms"):
        return store.list_vms()
    elif hasattr(store, "get_all_vms"):
        return store.get_all_vms()
    else:
        with store._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT vm_id, name, node_id, status, vcpus, memory_mb FROM vms")
            rows = cursor.fetchall()
            return [
                {
                    "vm_id": r[0],
                    "name": r[1],
                    "node_id": r[2],
                    "status": r[3],
                    "vcpus": r[4],
                    "memory_mb": r[5],
                }
                for r in rows
            ]

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    if not template_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard template file not found.",
        )
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))