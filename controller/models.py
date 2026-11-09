from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class NodeHeartbeat(BaseModel):
    node_id: str
    host: str = "127.0.0.1"
    port: int = 8001
    total_ram_mb: int
    free_ram_mb: int
    kvm_capable: Optional[bool] = False
    runtime_driver: Optional[str] = "mock_sandbox"

class NodeRecord(BaseModel):
    node_id: str
    host: str = "127.0.0.1"
    port: int = 8001
    total_ram_mb: int
    free_ram_mb: int
    last_heartbeat: datetime
    is_active: bool = True
    kvm_capable: bool = False
    runtime_driver: str = "mock_sandbox"

class VMCreateRequest(BaseModel):
    name: str
    vcpus: int
    memory_mb: int
    kernel_path: Optional[str] = None
    disk_path: Optional[str] = None

class VMRecord(BaseModel):
    vm_id: str
    name: str
    vcpus: int
    memory_mb: int
    node_id: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime