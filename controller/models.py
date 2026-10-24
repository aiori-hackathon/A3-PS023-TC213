from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class NodeHeartbeat(BaseModel):
    node_id: str
    host: str
    port: int = 8001
    total_ram_mb: int
    free_ram_mb: int

class NodeRecord(BaseModel):
    node_id: str
    host: str
    port: int
    total_ram_mb: int
    free_ram_mb: int
    last_heartbeat: datetime
    is_active: bool = True

class VMCreateRequest(BaseModel):
    name: str
    vcpus: int = Field(default=1, ge=1, le=16)
    memory_mb: int = Field(default=512, ge=128)
    kernel_path: Optional[str] = "/var/lib/cloud-hypervisor/vmlinux"
    disk_path: Optional[str] = None

class VMRecord(BaseModel):
    vm_id: str
    name: str
    vcpus: int
    memory_mb: int
    node_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, RUNNING, STOPPED, FAILED
    created_at: datetime
    updated_at: datetime