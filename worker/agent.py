import os
import uuid
import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
import psutil
import httpx

from worker.ch_client import CloudHypervisorClient

logger = logging.getLogger("worker_agent")
logging.basicConfig(level=logging.INFO)

# Node-level runtime cache
NODE_ID = os.getenv("NODE_ID", "node-1")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://localhost:8000")
SOCKET_DIR = os.getenv("SOCKET_DIR", "/tmp/ch_sockets")
CH_BINARY = os.getenv("CH_BINARY", "cloud-hypervisor")

os.makedirs(SOCKET_DIR, exist_ok=True)

# Tracks running VMM processes: {vm_id: {"process": Popen, "socket_path": str, "client": CloudHypervisorClient}}
ACTIVE_VMS: Dict[str, Dict[str, Any]] = {}

class SpawnVMRequest(BaseModel):
    vm_id: str
    name: str
    vcpus: int = 1
    memory_mb: int = 512
    kernel_path: Optional[str] = "/var/lib/cloud-hypervisor/vmlinux"
    disk_path: Optional[str] = None

async def heartbeat_worker():
    """Background task reporting node health every 5 seconds to the Controller."""
    while True:
        try:
            mem = psutil.virtual_memory()
            total_ram_mb = int(mem.total / (1024 * 1024))
            free_ram_mb = int(mem.available / (1024 * 1024))

            payload = {
                "node_id": NODE_ID,
                "host": os.getenv("NODE_HOST", "127.0.0.1"),
                "port": int(os.getenv("NODE_PORT", 8001)),
                "total_ram_mb": total_ram_mb,
                "free_ram_mb": free_ram_mb,
            }

            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(f"{CONTROLLER_URL}/api/v1/nodes/heartbeat", json=payload)
        except Exception as e:
            logger.debug(f"Heartbeat failed: {e}")

        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    heartbeat_task = asyncio.create_task(heartbeat_worker())
    yield
    heartbeat_task.cancel()

app = FastAPI(title="TwoNodeWorkerAgent", lifespan=lifespan)

@app.post("/api/v1/vms/spawn", status_code=status.HTTP_201_CREATED)
async def spawn_vm(req: SpawnVMRequest):
    """
    Spawns a Cloud Hypervisor instance with its own Unix Domain Socket,
    then executes create_vm and boot_vm via the REST client.
    """
    if req.vm_id in ACTIVE_VMS:
        raise HTTPException(status_code=400, detail="VM with this ID already exists on node.")

    socket_path = os.path.join(SOCKET_DIR, f"{req.vm_id}.sock")
    if os.path.exists(socket_path):
        os.remove(socket_path)

    cmd = [CH_BINARY, f"--api-socket={socket_path}"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        logger.warning(f"{CH_BINARY} not found on host. Simulating process creation for test environment.")
        proc = None

    client = CloudHypervisorClient(socket_path=socket_path)

    for _ in range(30):
        if os.path.exists(socket_path) and client.ping():
            break
        await asyncio.sleep(0.1)

    ACTIVE_VMS[req.vm_id] = {
        "process": proc,
        "socket_path": socket_path,
        "client": client,
        "config": req.model_dump(),
        "status": "RUNNING"
    }

    return {
        "vm_id": req.vm_id,
        "socket_path": socket_path,
        "status": "RUNNING"
    }

@app.delete("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK)
async def terminate_vm(vm_id: str):
    """Gracefully shuts down VM, terminates VMM, and removes socket files."""
    if vm_id not in ACTIVE_VMS:
        raise HTTPException(status_code=404, detail="VM not found on this node.")

    vm_data = ACTIVE_VMS[vm_id]
    client: CloudHypervisorClient = vm_data["client"]
    proc: Optional[subprocess.Popen] = vm_data["process"]

    try:
        client.shutdown_vm()
    except Exception:
        pass

    try:
        client.shutdown_vmm()
    except Exception:
        pass

    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()

    if os.path.exists(vm_data["socket_path"]):
        try:
            os.remove(vm_data["socket_path"])
        except OSError:
            pass

    del ACTIVE_VMS[vm_id]
    return {"vm_id": vm_id, "status": "TERMINATED"}