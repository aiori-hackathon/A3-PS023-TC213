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
    store.upsert_node(NodeHeartbeat(node_id="node-1", host="10.0.0.1", port=8001, total_ram_mb=4096, free_ram_mb=2048))
    # Register Node 2: 4096 MB free
    store.upsert_node(NodeHeartbeat(node_id="node-2", host="10.0.0.2", port=8002, total_ram_mb=8192, free_ram_mb=4096))

    scheduler = Scheduler(store)
    # Request 1024 MB
    chosen = await scheduler.select_node(required_ram_mb=1024)
    assert chosen.node_id == "node-2"

@pytest.mark.anyio
async def test_scheduler_respects_512mb_host_reserve(store):
    # Node has 1024 MB free. Usable = 1024 - 512 = 512 MB.
    store.upsert_node(NodeHeartbeat(node_id="node-1", host="10.0.0.1", port=8001, total_ram_mb=2048, free_ram_mb=1024))

    scheduler = Scheduler(store)

    # 512 MB requested fits exactly in usable space
    node = await scheduler.select_node(required_ram_mb=512)
    assert node.node_id == "node-1"

    # 513 MB requested must raise InsufficientCapacityError
    with pytest.raises(InsufficientCapacityError):
        await scheduler.select_node(required_ram_mb=513)

@pytest.mark.anyio
async def test_scheduler_evicts_stale_heartbeat_node(store):
    scheduler = Scheduler(store)
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(seconds=25)

    # node-1 is healthy and recent
    store.upsert_node(NodeHeartbeat(
        node_id="node-1", host="10.0.0.1", port=8001,
        total_ram_mb=4096, free_ram_mb=2048
    ))

    # node-2 has more RAM, but its heartbeat timed out
    store.upsert_node(NodeHeartbeat(
        node_id="node-2", host="10.0.0.2", port=8002,
        total_ram_mb=8192, free_ram_mb=6144
    ))
    # Manually backdate node-2 in SQLite to simulate unresponsiveness
    with store._get_conn() as conn:
        conn.execute("UPDATE nodes SET last_heartbeat = ? WHERE node_id = ?", (stale_time.isoformat(), "node-2"))
        conn.commit()

    # The scheduler must bypass dead node-2 and select active node-1
    selected = await scheduler.select_node(required_ram_mb=1024)
    assert selected.node_id == "node-1"

@pytest.mark.anyio
async def test_scheduler_raises_when_all_nodes_offline(store):
    scheduler = Scheduler(store)
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=30)

    store.upsert_node(NodeHeartbeat(
        node_id="node-1", host="10.0.0.1", port=8001,
        total_ram_mb=4096, free_ram_mb=2048
    ))
    with store._get_conn() as conn:
        conn.execute("UPDATE nodes SET last_heartbeat = ? WHERE node_id = ?", (stale_time.isoformat(), "node-1"))
        conn.commit()

    with pytest.raises(NoHealthyNodesError):
        await scheduler.select_node(required_ram_mb=512)