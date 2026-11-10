import os
import uuid
import httpx
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from controller.models import NodeHeartbeat, NodeRecord, VMCreateRequest, VMRecord
from controller.store import MetadataStore
from controller.scheduler import Scheduler, InsufficientCapacityError, NoHealthyNodesError
from controller.security import verify_controller_token, WORKER_SHARED_SECRET

app = FastAPI(title="TwoNodeCloudHypervisorController")

templates = Jinja2Templates(directory="controller/templates")
store = MetadataStore()
scheduler = Scheduler(store)

@app.get("/healthz", status_code=status.HTTP_200_OK)
def health_check():
    return {"status": "ok", "service": "controller"}

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.post("/api/v1/nodes/heartbeat", status_code=status.HTTP_200_OK)
def heartbeat(node_data: NodeHeartbeat):
    store.upsert_node(node_data)
    return {"status": "heartbeat_acknowledged", "node_id": node_data.node_id}

@app.get("/api/v1/nodes", response_model=list[NodeRecord], dependencies=[Depends(verify_controller_token)])
def list_nodes():
    return store.list_nodes()

@app.get("/api/v1/vms", response_model=list[VMRecord], dependencies=[Depends(verify_controller_token)])
def list_vms():
    return store.list_vms()

@app.get("/api/v1/vms/{vm_id}", response_model=VMRecord, dependencies=[Depends(verify_controller_token)])
def get_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found.")
    return vm

@app.post("/api/v1/vms", response_model=VMRecord, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_controller_token)])
async def create_vm(req: VMCreateRequest):
    try:
        chosen_node = await scheduler.select_node(req.memory_mb)
    except NoHealthyNodesError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except InsufficientCapacityError as e:
        raise HTTPException(status_code=507, detail=str(e))

    vm_id = f"vm-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    
    vm_record = VMRecord(
        vm_id=vm_id,
        name=req.name,
        vcpus=req.vcpus,
        memory_mb=req.memory_mb,
        node_id=chosen_node.node_id,
        status="CREATING",
        created_at=now,
        updated_at=now
    )
    store.insert_vm(vm_record)

    worker_payload = {
        "vm_id": vm_id,
        "name": req.name,
        "vcpus": req.vcpus,
        "memory_mb": req.memory_mb,
        "kernel_path": req.kernel_path,
        "disk_path": req.disk_path
    }

    worker_url = f"http://{chosen_node.host}:{chosen_node.port}/api/v1/vms/spawn"
    headers = {"X-Worker-Token": WORKER_SHARED_SECRET}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(worker_url, json=worker_payload, headers=headers)
            if resp.status_code != 201:
                store.update_vm_status(vm_id, "ERROR")
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
        except httpx.RequestError as e:
            store.update_vm_status(vm_id, "ERROR")
            raise HTTPException(status_code=502, detail=f"Failed to communicate with worker: {e}")

    store.update_vm_status(vm_id, "RUNNING")
    return store.get_vm(vm_id)

@app.post("/api/v1/vms/{vm_id}/start", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_controller_token)])
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

    headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"http://{node.host}:{node.port}/api/v1/vms/{vm_id}/start", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to communicate with worker: {e}")

    store.update_vm_status(vm_id, "RUNNING")
    return {"vm_id": vm_id, "status": "RUNNING"}

@app.post("/api/v1/vms/{vm_id}/stop", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_controller_token)])
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

    headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"http://{node.host}:{node.port}/api/v1/vms/{vm_id}/stop", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to communicate with worker: {e}")

    store.update_vm_status(vm_id, "STOPPED")
    return {"vm_id": vm_id, "status": "STOPPED"}

@app.delete("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_controller_token)])
async def delete_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found.")

    node = store.get_node(vm.node_id) if vm.node_id else None
    if node:
        headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.delete(f"http://{node.host}:{node.port}/api/v1/vms/{vm_id}", headers=headers)
            except httpx.RequestError:
                pass

    store.update_vm_status(vm_id, "DELETED")
    return {"vm_id": vm_id, "status": "DELETED"}
