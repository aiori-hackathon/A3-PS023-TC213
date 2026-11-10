from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Set
from pydantic import BaseModel, Field, computed_field
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
    name: str = Field(..., min_length=1, max_length=64, description="Human-readable VM name")
    vcpus: int = Field(..., ge=1, le=4, description="vCPU count restricted between 1 and 4")
    memory_mb: int = Field(..., ge=128, le=2048, description="Memory restricted between 128MB and 2048MB")
    kernel_path: Optional[str] = None
    disk_path: Optional[str] = None
class VMState(str, Enum):
    CREATING = "CREATING"
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    DELETED = "DELETED"
    ERROR = "ERROR"

# Explicit directed graph of allowed lifecycle transitions
LEGAL_TRANSITIONS: dict[VMState, Set[VMState]] = {
    VMState.CREATING: {VMState.CREATED, VMState.ERROR},
    VMState.CREATED: {VMState.RUNNING, VMState.DELETED, VMState.ERROR},
    VMState.RUNNING: {VMState.STOPPED, VMState.DELETED, VMState.ERROR},
    VMState.STOPPED: {VMState.RUNNING, VMState.DELETED, VMState.ERROR},
    VMState.ERROR: {VMState.DELETED},
    VMState.DELETED: set(),
}

def validate_transition(current: str, target: str) -> bool:
    try:
        curr_enum = VMState(current)
        targ_enum = VMState(target)
        return targ_enum in LEGAL_TRANSITIONS.get(curr_enum, set())
    except ValueError:
        return False

class VMRecord(BaseModel):
    vm_id: str
    name: str
    vcpus: int
    memory_mb: int
    node_id: Optional[str] = None
    status: str = VMState.CREATING.value
    created_at: datetime
    updated_at: datetime