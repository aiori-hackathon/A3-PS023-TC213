from controller.metrics import generate_prometheus_metrics
from fastapi.responses import PlainTextResponse
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field
import httpx

from controller.security import verify_admin_token, verify_worker_token
from controller.audit import audit_log
from controller.db import store
from controller.reconciler import cluster_ha_loop

logger = logging.getLogger("controller")
logging.basicConfig(level=logging.INFO)

WORKER_SHARED_SECRET = "default-worker-secret"

class NodeHeartbeatRequest(BaseModel):
    node_id: str
    host: str
    port: int
    total_ram_mb: int
    free_ram_mb: int
    kvm_capable: Optional[bool] = True
    runtime_driver: Optional[str] = "kvm"

class VMCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    vcpus: int = Field(1, ge=1, le=4)
    memory_mb: int = Field(512, ge=128, le=2048)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ha_task = asyncio.create_task(cluster_ha_loop())
    yield
    ha_task.cancel()

app = FastAPI(title="TwoNodeCloudHypervisorController", lifespan=lifespan)
scheduler_lock = asyncio.Lock()

@app.post("/api/v1/nodes/heartbeat", status_code=status.HTTP_200_OK)
async def node_heartbeat(hb: NodeHeartbeatRequest):
    data = hb.model_dump()
    data["health_status"] = "ONLINE"
    data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
    store.upsert_node(data)
    return {"status": "ACK", "node_id": hb.node_id}

@app.get("/api/v1/nodes", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_admin_token)])
async def list_nodes():
    nodes = store.get_all_nodes()
    for n in nodes:
        n["kvm_capable"] = bool(n["kvm_capable"])
        n["is_active"] = (n["health_status"] == "ONLINE")
    return nodes

@app.post("/api/v1/vms", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_admin_token)])
async def provision_vm(req: VMCreateRequest):
    async with scheduler_lock:
        nodes = [n for n in store.get_all_nodes() if n["health_status"] == "ONLINE"]
        if not nodes:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No healthy nodes registered in cluster."
            )

        eligible_nodes = [n for n in nodes if n["free_ram_mb"] >= req.memory_mb]
        if not eligible_nodes:
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail="Insufficient memory headroom available across cluster nodes."
            )

        selected_node = max(eligible_nodes, key=lambda n: n["free_ram_mb"])
        vm_id = f"vm-{uuid.uuid4().hex[:8]}"

        target_url = f"http://{selected_node['host']}:{selected_node['port']}"
        spawn_payload = {
            "vm_id": vm_id,
            "name": req.name,
            "vcpus": req.vcpus,
            "memory_mb": req.memory_mb
        }

        headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{target_url}/api/v1/vms/spawn",
                    json=spawn_payload,
                    headers=headers
                )
                if resp.status_code != 201:
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"Worker agent failed provisioning: {resp.text}"
                    )
                worker_data = resp.json()
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed communicating with target worker: {e}"
            )

        now = datetime.now(timezone.utc).isoformat()
        vm_record = {
            "vm_id": vm_id,
            "name": req.name,
            "vcpus": req.vcpus,
            "memory_mb": req.memory_mb,
            "node_id": selected_node["node_id"],
            "status": "RUNNING",
            "ip": worker_data.get("ip"),
            "mac": worker_data.get("mac"),
            "created_at": now,
            "updated_at": now
        }
        store.upsert_vm(vm_record)
        audit_log("PROVISION_VM", f"Provisioned {vm_id} on {selected_node['node_id']}")
        return vm_record

@app.get("/api/v1/vms", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_admin_token)])
async def list_vms():
    return store.get_all_vms()

@app.get("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_admin_token)])
async def get_vm_details(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm or vm["status"] == "DELETED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")
    return vm

@app.post("/api/v1/vms/{vm_id}/stop", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_admin_token)])
async def stop_cluster_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm or vm["status"] == "DELETED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")

    if vm["status"] == "STOPPED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"VM {vm_id} is already STOPPED.")
    if vm["status"] != "RUNNING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot stop VM from state {vm['status']}.")

    node = store.get_node(vm["node_id"])
    if not node:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Associated node missing.")

    target_url = f"http://{node['host']}:{node['port']}"
    headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{target_url}/api/v1/vms/{vm_id}/stop", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Worker communication failure: {e}")

    vm["status"] = "STOPPED"
    vm["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.upsert_vm(vm)
    audit_log("STOP_VM", f"Stopped {vm_id} on {vm['node_id']}")
    return {"vm_id": vm_id, "status": "STOPPED"}

@app.post("/api/v1/vms/{vm_id}/start", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_admin_token)])
async def start_cluster_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm or vm["status"] == "DELETED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")

    if vm["status"] == "RUNNING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"VM {vm_id} is already RUNNING.")
    if vm["status"] not in ("CREATED", "STOPPED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot start VM from state {vm['status']}.")

    node = store.get_node(vm["node_id"])
    if not node or node["health_status"] != "ONLINE":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Assigned worker node is not online.")

    target_url = f"http://{node['host']}:{node['port']}"
    headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{target_url}/api/v1/vms/{vm_id}/start", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Worker communication failure: {e}")

    vm["status"] = "RUNNING"
    vm["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.upsert_vm(vm)
    audit_log("START_VM", f"Started {vm_id} on {vm['node_id']}")
    return {"vm_id": vm_id, "status": "RUNNING"}

@app.delete("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_admin_token)])
async def delete_cluster_vm(vm_id: str):
    vm = store.get_vm(vm_id)
    if not vm or vm["status"] == "DELETED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")

    node = store.get_node(vm["node_id"])
    if node and node["health_status"] == "ONLINE":
        target_url = f"http://{node['host']}:{node['port']}"
        headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.delete(f"{target_url}/api/v1/vms/{vm_id}", headers=headers)
        except Exception as e:
            logger.warning(f"Worker deletion warning for {vm_id}: {e}")

    store.delete_vm_record(vm_id)
    audit_log("DELETE_VM", f"Deleted {vm_id} from {vm['node_id']}")
    return {"vm_id": vm_id, "status": "DELETED"}

@app.get("/api/v1/metrics", response_class=PlainTextResponse)
async def cluster_metrics():
    return generate_prometheus_metrics()

from fastapi.responses import HTMLResponse
from pathlib import Path

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    dashboard_file = Path("controller/templates/dashboard.html")
    if not dashboard_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard template missing.")
    return HTMLResponse(content=dashboard_file.read_text())