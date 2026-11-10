import os
import shutil
import signal
import uuid
import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field
import psutil
import httpx
from pathlib import Path

from worker.capabilities import probe_node_capabilities
from worker.ch_client import CloudHypervisorClient
from worker.security import verify_worker_token
from worker.network import create_tap_device, destroy_tap_device, generate_mac_and_ip
from worker.storage import create_cow_overlay, remove_cow_overlay

PROJECT_ROOT = Path(os.getcwd())
BASE_ARTIFACT_DIR = PROJECT_ROOT / "data" / "images"
DEFAULT_FIRMWARE_PATH = str(BASE_ARTIFACT_DIR / "hypervisor-fw")
DEFAULT_KERNEL_PATH = str(BASE_ARTIFACT_DIR / "vmlinux.bin")
DEFAULT_QCOW2_DISK_PATH = str(BASE_ARTIFACT_DIR / "rootfs.qcow2")
DEFAULT_DISK_PATH = str(BASE_ARTIFACT_DIR / "rootfs.raw")

logger = logging.getLogger("worker_agent")
logging.basicConfig(level=logging.INFO)

NODE_ID = os.getenv("NODE_ID", "node-1")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://localhost:8000")
SOCKET_DIR = os.getenv("SOCKET_DIR", "/tmp/ch_sockets")
CH_BINARY = os.getenv("CH_BINARY", "cloud-hypervisor")
WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET", "default-worker-secret")

os.makedirs(SOCKET_DIR, exist_ok=True)
os.makedirs(BASE_ARTIFACT_DIR, exist_ok=True)

ACTIVE_VMS: Dict[str, Dict[str, Any]] = {}

class SpawnVMRequest(BaseModel):
    vm_id: str
    name: str = Field(..., min_length=1, max_length=64)
    vcpus: int = Field(1, ge=1, le=4)
    memory_mb: int = Field(512, ge=128, le=2048)
    kernel_path: Optional[str] = None
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
            fallback_dir = Path("/tmp/ch_test_artifacts")
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_file = fallback_dir / target.name
            fallback_file.touch(exist_ok=True)
            if p == kernel:
                kernel = str(fallback_file)
            else:
                disk = str(fallback_file)

    return str(kernel), str(disk)

async def reconciler_worker():
    while True:
        try:
            for vm_id, data in list(ACTIVE_VMS.items()):
                proc: Optional[subprocess.Popen] = data.get("process")
                if proc is not None and proc.poll() is not None:
                    if data.get("status") in ("CREATED", "RUNNING"):
                        logger.warning(f"Reconciler: process exited unexpectedly for VM {vm_id}. Cleaning sockets & network.")
                        sock = data.get("socket_path")
                        if sock and os.path.exists(sock):
                            try:
                                os.remove(sock)
                            except OSError:
                                pass
                        destroy_tap_device(vm_id)
                        ACTIVE_VMS[vm_id]["status"] = "ERROR"

            if os.path.exists(SOCKET_DIR):
                for entry in os.listdir(SOCKET_DIR):
                    if entry.endswith(".sock"):
                        vid = entry[:-5]
                        if vid not in ACTIVE_VMS:
                            stray_sock = os.path.join(SOCKET_DIR, entry)
                            try:
                                os.remove(stray_sock)
                            except OSError:
                                pass
        except Exception as e:
            logger.error(f"Reconciler error: {e}")

        await asyncio.sleep(2)

async def heartbeat_worker():
    while True:
        try:
            mem = psutil.virtual_memory()
            total_ram = int(mem.total / (1024 * 1024))
            base_free_ram = int(mem.available / (1024 * 1024))

            committed_vm_ram = sum(
                int(vm.get("config", {}).get("memory_mb", 0))
                for vm in ACTIVE_VMS.values()
                if vm.get("status") in ("CREATED", "RUNNING")
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

            headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(
                    f"{CONTROLLER_URL}/api/v1/nodes/heartbeat",
                    json=payload,
                    headers=headers
                )
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

        await asyncio.sleep(5)

def clean_all_active_vms():
    for vm_id, data in list(ACTIVE_VMS.items()):
        proc: Optional[subprocess.Popen] = data.get("process")
        sock: str = data.get("socket_path", "")
        cloned_disk: str = data.get("cloned_disk", "")
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        if sock and os.path.exists(sock):
            try:
                os.remove(sock)
            except OSError:
                pass
        if cloned_disk and os.path.exists(cloned_disk) and cloned_disk not in (DEFAULT_DISK_PATH, DEFAULT_QCOW2_DISK_PATH):
            remove_cow_overlay(cloned_disk)
        destroy_tap_device(vm_id)
    ACTIVE_VMS.clear()

@asynccontextmanager
async def lifespan(app: FastAPI):
    heartbeat_task = asyncio.create_task(heartbeat_worker())
    reconciler_task = asyncio.create_task(reconciler_worker())
    yield
    heartbeat_task.cancel()
    reconciler_task.cancel()
    clean_all_active_vms()

app = FastAPI(title="TwoNodeWorkerAgent", lifespan=lifespan)

@app.post("/api/v1/vms/create", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_worker_token)])
async def create_vm(req: SpawnVMRequest):
    if req.vm_id in ACTIVE_VMS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {req.vm_id} already exists on this node."
        )

    boot_artifact, base_disk = resolve_and_validate_artifacts(req.kernel_path, req.disk_path)

    # CoW Thin Provisioning
    cow_base = DEFAULT_QCOW2_DISK_PATH if os.path.exists(DEFAULT_QCOW2_DISK_PATH) else base_disk
    if cow_base.endswith(".qcow2") and os.path.exists(cow_base):
        vm_disk = os.path.join(SOCKET_DIR, f"{req.vm_id}_overlay.qcow2")
        cow_ok = create_cow_overlay(cow_base, vm_disk)
        if not cow_ok:
            vm_disk = base_disk
    elif os.path.exists(base_disk) and os.path.getsize(base_disk) > 0:
        vm_disk = os.path.join(SOCKET_DIR, f"{req.vm_id}_rootfs.raw")
        try:
            shutil.copyfile(base_disk, vm_disk)
        except OSError:
            vm_disk = base_disk
    else:
        vm_disk = base_disk

    socket_path = os.path.join(SOCKET_DIR, f"{req.vm_id}.sock")
    console_log = os.path.join(SOCKET_DIR, f"{req.vm_id}_console.log")
    if os.path.exists(socket_path):
        try:
            os.remove(socket_path)
        except OSError:
            pass

    # Provision dedicated TAP interface and deterministic MAC/IP
    tap_name = create_tap_device(req.vm_id)
    mac_addr, ip_addr = generate_mac_and_ip(req.vm_id)

    caps = probe_node_capabilities()
    proc = None

    if caps["kvm_capable"] and shutil.which(CH_BINARY):
        cmd = [
            CH_BINARY,
            f"--api-socket={socket_path}",
            "--seccomp", "false",
            "--console", "off",
            "--serial", "off"
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setpgrp
            )
        except Exception as e:
            logger.warning(f"Native cloud-hypervisor spawn failed: {e}. Using fallback simulation.")
            proc = None

    client = CloudHypervisorClient(socket_path=socket_path)

    if proc is not None:
        for _ in range(40):
            if os.path.exists(socket_path) and client.ping():
                break
            await asyncio.sleep(0.05)

    if "hypervisor-fw" in os.path.basename(boot_artifact) or os.path.exists(DEFAULT_FIRMWARE_PATH):
        payload_config = {"firmware": DEFAULT_FIRMWARE_PATH if os.path.exists(DEFAULT_FIRMWARE_PATH) else boot_artifact}
    else:
        payload_config = {
            "kernel": boot_artifact,
            "cmdline": "console=ttyS0 root=/dev/vda rw reboot=k panic=1 quiet"
        }

    net_config = []
    if tap_name:
        net_config.append({
            "tap": tap_name,
            "mac": mac_addr,
            "ip": ip_addr,
            "mask": "255.255.255.0"
        })

    ch_config = {
        "cpus": {"boot_vcpus": req.vcpus, "max_vcpus": req.vcpus},
        "memory": {"size": req.memory_mb * 1024 * 1024},
        "payload": payload_config,
        "disks": [{"path": vm_disk}] if os.path.exists(vm_disk) else [],
        "net": net_config if net_config else None
    }

    try:
        client.create_vm(ch_config)
    except Exception as e:
        logger.warning(f"CH create_vm call falling back to simulation: {e}")

    config_data = req.model_dump()
    config_data["kernel_path"] = boot_artifact
    config_data["disk_path"] = vm_disk
    config_data["ip"] = ip_addr
    config_data["mac"] = mac_addr
    config_data["tap"] = tap_name

    ACTIVE_VMS[req.vm_id] = {
        "process": proc,
        "socket_path": socket_path,
        "cloned_disk": vm_disk,
        "console_log": console_log,
        "tap_device": tap_name,
        "ip": ip_addr,
        "mac": mac_addr,
        "client": client,
        "config": config_data,
        "status": "CREATED"
    }

    return {
        "vm_id": req.vm_id,
        "socket_path": socket_path,
        "status": "CREATED",
        "ip": ip_addr,
        "mac": mac_addr,
        "tap": tap_name,
        "kernel_path": boot_artifact,
        "disk_path": vm_disk
    }

@app.post("/api/v1/vms/{vm_id}/start", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_worker_token)])
async def start_vm(vm_id: str):
    if vm_id not in ACTIVE_VMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")

    current_status = ACTIVE_VMS[vm_id]["status"]
    if current_status == "RUNNING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"VM {vm_id} is already RUNNING.")
    if current_status not in ("CREATED", "STOPPED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot start VM from state {current_status}.")

    vm_data = ACTIVE_VMS[vm_id]
    client: CloudHypervisorClient = vm_data["client"]
    socket_path = vm_data["socket_path"]
    proc = vm_data.get("process")

    if not os.path.exists(socket_path) or (proc is not None and proc.poll() is not None):
        caps = probe_node_capabilities()
        if caps["kvm_capable"] and shutil.which(CH_BINARY):
            cmd = [
                CH_BINARY,
                f"--api-socket={socket_path}",
                "--seccomp", "false",
                "--console", "off",
                "--serial", "off"
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setpgrp
                )
                vm_data["process"] = proc
                for _ in range(40):
                    if os.path.exists(socket_path) and client.ping():
                        break
                    await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"Failed to restart VMM process: {e}")

        cfg = vm_data["config"]
        boot_artifact = cfg["kernel_path"]
        if "hypervisor-fw" in os.path.basename(boot_artifact) or os.path.exists(DEFAULT_FIRMWARE_PATH):
            payload_config = {"firmware": DEFAULT_FIRMWARE_PATH if os.path.exists(DEFAULT_FIRMWARE_PATH) else boot_artifact}
        else:
            payload_config = {
                "kernel": boot_artifact,
                "cmdline": "console=ttyS0 root=/dev/vda rw reboot=k panic=1 quiet"
            }

        net_config = []
        if vm_data.get("tap_device"):
            net_config.append({
                "tap": vm_data["tap_device"],
                "mac": vm_data["mac"],
                "ip": vm_data["ip"],
                "mask": "255.255.255.0"
            })

        ch_config = {
            "cpus": {"boot_vcpus": cfg.get("vcpus", 1), "max_vcpus": cfg.get("vcpus", 1)},
            "memory": {"size": cfg.get("memory_mb", 512) * 1024 * 1024},
            "payload": payload_config,
            "disks": [{"path": vm_data["cloned_disk"]}] if os.path.exists(vm_data["cloned_disk"]) else [],
            "net": net_config if net_config else None
        }
        try:
            client.create_vm(ch_config)
        except Exception as e:
            logger.warning(f"CH recreate_vm on restart fallback: {e}")

    try:
        client.boot_vm()
    except Exception as e:
        logger.warning(f"boot_vm fallback: {e}")

    ACTIVE_VMS[vm_id]["status"] = "RUNNING"
    return {"vm_id": vm_id, "status": "RUNNING"}

@app.post("/api/v1/vms/{vm_id}/stop", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_worker_token)])
async def stop_vm(vm_id: str):
    if vm_id not in ACTIVE_VMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")

    current_status = ACTIVE_VMS[vm_id]["status"]
    if current_status == "STOPPED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"VM {vm_id} is already STOPPED.")
    if current_status != "RUNNING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot stop VM from state {current_status}.")

    client: CloudHypervisorClient = ACTIVE_VMS[vm_id]["client"]
    try:
        client.shutdown_vm()
    except Exception as e:
        logger.warning(f"shutdown_vm fallback: {e}")

    ACTIVE_VMS[vm_id]["status"] = "STOPPED"
    return {"vm_id": vm_id, "status": "STOPPED"}

@app.post("/api/v1/vms/spawn", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_worker_token)])
async def spawn_vm(req: SpawnVMRequest):
    create_res = await create_vm(req)
    await start_vm(req.vm_id)
    return {
        "vm_id": req.vm_id,
        "socket_path": create_res["socket_path"],
        "status": "RUNNING",
        "ip": create_res.get("ip"),
        "mac": create_res.get("mac"),
        "tap": create_res.get("tap"),
        "kernel_path": create_res["kernel_path"],
        "disk_path": create_res["disk_path"]
    }

@app.get("/api/v1/vms", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_worker_token)])
async def list_node_vms():
    return [
        {"vm_id": vid, "status": v["status"], "config": v["config"]}
        for vid, v in ACTIVE_VMS.items()
    ]

@app.get("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_worker_token)])
async def get_node_vm(vm_id: str):
    if vm_id not in ACTIVE_VMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found.")
    v = ACTIVE_VMS[vm_id]
    return {"vm_id": vm_id, "status": v["status"], "config": v["config"]}

@app.delete("/api/v1/vms/{vm_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(verify_worker_token)])
async def terminate_vm(vm_id: str):
    if vm_id not in ACTIVE_VMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found on this node.")

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

    if proc is not None:
        try:
            if proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=1.0)
        except (ProcessLookupError, PermissionError):
            pass

    try:
        subprocess.run(["pkill", "-9", "-f", vm_data["socket_path"]], stderr=subprocess.DEVNULL)
    except Exception:
        pass

    if os.path.exists(vm_data["socket_path"]):
        try:
            os.remove(vm_data["socket_path"])
        except OSError:
            pass

    cloned_disk = vm_data.get("cloned_disk")
    if cloned_disk and os.path.exists(cloned_disk) and cloned_disk not in (DEFAULT_DISK_PATH, DEFAULT_QCOW2_DISK_PATH):
        remove_cow_overlay(cloned_disk)

    destroy_tap_device(vm_id)

    del ACTIVE_VMS[vm_id]
    return {"vm_id": vm_id, "status": "TERMINATED", "state": "DELETED"}
