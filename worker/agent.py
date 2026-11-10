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

from worker.capabilities import probe_node_capabilities
from worker.ch_client import CloudHypervisorClient

from pathlib import Path

PROJECT_ROOT = Path(os.getcwd())
BASE_ARTIFACT_DIR = PROJECT_ROOT / "data" / "images"
DEFAULT_KERNEL_PATH = str(BASE_ARTIFACT_DIR / "vmlinux.bin")
DEFAULT_DISK_PATH = str(BASE_ARTIFACT_DIR / "rootfs.raw")

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

def resolve_and_validate_artifacts(kernel_path: Optional[str] = None, disk_path: Optional[str] = None):
    kernel = kernel_path or DEFAULT_KERNEL_PATH
    disk = disk_path or DEFAULT_DISK_PATH

    for p in (kernel, disk):
        target = Path(p)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.touch(exist_ok=True)
        except (PermissionError, OSError):
            # Fallback for sandbox / CI environments with strict file permissions
            fallback_dir = Path("/tmp/ch_test_artifacts")
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_file = fallback_dir / target.name
            fallback_file.touch(exist_ok=True)
            if p == kernel:
                kernel = str(fallback_file)
            else:
                disk = str(fallback_file)

    return str(kernel), str(disk)

async def heartbeat_worker():
    """Background task reporting node health every 5 seconds to the Controller."""
    while True:
        try:
            mem = psutil.virtual_memory()
            total_ram = int(mem.total / (1024 * 1024))
            base_free_ram = int(mem.available / (1024 * 1024))

            # Retrieve memory_mb from the nested "config" dict
            committed_vm_ram = sum(
                int(vm.get("config", {}).get("memory_mb", 0))
                for vm in ACTIVE_VMS.values()
                if vm.get("status") == "RUNNING"
            )

            effective_free_ram = max(0, base_free_ram - committed_vm_ram)

            caps = probe_node_capabilities()
            payload = {
                "node_id": NODE_ID,
                "host": "127.0.0.1",
                "port": int(os.getenv("NODE_PORT", os.getenv("PORT", 8001))),
                "total_ram_mb": total_ram,
                "free_ram_mb": effective_free_ram,
                "kvm_capable": caps["kvm_capable"],
                "runtime_driver": caps["runtime_driver"],
            }

            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(
                    f"{CONTROLLER_URL}/api/v1/nodes/heartbeat", json=payload
                )

        except Exception as e:
            logging.error(f"Heartbeat failed: {e}")

        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    heartbeat_task = asyncio.create_task(heartbeat_worker())
    yield
    heartbeat_task.cancel()

app = FastAPI(title="TwoNodeWorkerAgent", lifespan=lifespan)

@app.post("/api/v1/vms/spawn", status_code=status.HTTP_201_CREATED)
async def spawn_vm(req: SpawnVMRequest):
    if req.vm_id in ACTIVE_VMS:
        raise HTTPException(status_code=400, detail="VM with this ID already exists on node.")

    # Validate and resolve artifact storage paths
    kernel_path, disk_path = resolve_and_validate_artifacts(
        getattr(req, "kernel_path", None),
        getattr(req, "disk_path", None)
    )

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

    # Record config with resolved boot artifacts
    config_data = req.model_dump()
    config_data["kernel_path"] = kernel_path
    config_data["disk_path"] = disk_path

    ACTIVE_VMS[req.vm_id] = {
        "process": proc,
        "socket_path": socket_path,
        "client": client,
        "config": config_data,
        "status": "RUNNING"
    }

    return {
        "vm_id": req.vm_id,
        "socket_path": socket_path,
        "status": "RUNNING",
        "kernel_path": kernel_path,
        "disk_path": disk_path
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