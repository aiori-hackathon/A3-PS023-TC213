from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, computed_field

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

    @computed_field
    @property
    def health_status(self) -> str:
        """Determines health based on heartbeat age."""
        now = datetime.now(timezone.utc)
        # Handle naive vs aware datetimes safely
        hb = self.last_heartbeat
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        age = (now - hb).total_seconds()
        if age <= 10.0:
            return "ONLINE"
        elif age <= 20.0:
            return "DEGRADED"
        return "OFFLINE"

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