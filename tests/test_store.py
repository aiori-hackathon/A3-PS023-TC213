import os
import pytest
from datetime import datetime, timezone
from controller.models import NodeHeartbeat, VMRecord
from controller.store import MetadataStore

TEST_DB = "test_controller.db"

@pytest.fixture
def store():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = MetadataStore(db_path=TEST_DB)
    yield db
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def test_node_heartbeat_upsert(store):
    hb = NodeHeartbeat(
        node_id="node-1",
        host="192.168.1.10",
        port=8001,
        total_ram_mb=8192,
        free_ram_mb=4096
    )
    store.upsert_node(hb)
    nodes = store.list_nodes()
    assert len(nodes) == 1
    assert nodes[0].node_id == "node-1"
    assert nodes[0].free_ram_mb == 4096

def test_vm_lifecycle_tracking(store):
    vm = VMRecord(
        vm_id="vm-001",
        name="test-instance",
        vcpus=2,
        memory_mb=1024,
        status="PENDING",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    store.insert_vm(vm)
    record = store.get_vm("vm-001")
    assert record is not None
    assert record.status == "PENDING"

    store.update_vm_status("vm-001", "RUNNING", node_id="node-1")
    updated = store.get_vm("vm-001")
    assert updated.status == "RUNNING"
    assert updated.node_id == "node-1"