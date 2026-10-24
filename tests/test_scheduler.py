import os
import pytest
from datetime import datetime, timezone, timedelta
from controller.store import MetadataStore
from controller.models import NodeHeartbeat
from controller.scheduler import Scheduler, InsufficientCapacityError, NoHealthyNodesError

TEST_DB = "test_sched.db"

@pytest.fixture
def store():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = MetadataStore(db_path=TEST_DB)
    yield db
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

@pytest.mark.anyio
async def test_scheduler_picks_node_with_most_ram(store):
    # Register Node 1: 2048 MB free
    store.upsert_node(NodeHeartbeat(node_id="node-1", host="10.0.0.1", total_ram_mb=4096, free_ram_mb=2048))
    # Register Node 2: 4096 MB free
    store.upsert_node(NodeHeartbeat(node_id="node-2", host="10.0.0.2", total_ram_mb=8192, free_ram_mb=4096))

    scheduler = Scheduler(store)
    # Request 1024 MB
    chosen = await scheduler.select_node(required_ram_mb=1024)
    assert chosen.node_id == "node-2"

@pytest.mark.anyio
async def test_scheduler_respects_512mb_host_reserve(store):
    # Node has 1024 MB free. Usable = 1024 - 512 = 512 MB.
    store.upsert_node(NodeHeartbeat(node_id="node-1", host="10.0.0.1", total_ram_mb=2048, free_ram_mb=1024))

    scheduler = Scheduler(store)

    # 512 MB requested fits exactly in usable space
    node = await scheduler.select_node(required_ram_mb=512)
    assert node.node_id == "node-1"

    # 513 MB requested must raise InsufficientCapacityError
    with pytest.raises(InsufficientCapacityError):
        await scheduler.select_node(required_ram_mb=513)