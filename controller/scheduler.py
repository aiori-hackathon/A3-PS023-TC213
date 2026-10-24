import asyncio
from datetime import datetime, timezone
from typing import Optional
from controller.store import MetadataStore
from controller.models import NodeRecord

HOST_RESERVED_RAM_MB = 512
HEARTBEAT_TIMEOUT_SECONDS = 15

class InsufficientCapacityError(Exception):
    pass

class NoHealthyNodesError(Exception):
    pass

class Scheduler:
    def __init__(self, store: MetadataStore):
        self.store = store
        self._lock = asyncio.Lock()

    async def select_node(self, required_ram_mb: int) -> NodeRecord:
        """
        Thread-safe node placement engine.
        Applies host reserve margin and selects the node with greatest available capacity.
        """
        async with self._lock:
            nodes = self.store.list_nodes()
            if not nodes:
                raise NoHealthyNodesError("No compute nodes registered in the cluster.")

            now = datetime.now(timezone.utc)
            healthy_candidates = []

            for node in nodes:
                # Ensure timezone comparability
                node_hb = node.last_heartbeat
                if node_hb.tzinfo is None:
                    node_hb = node_hb.replace(tzinfo=timezone.utc)

                age_seconds = (now - node_hb).total_seconds()
                if age_seconds > HEARTBEAT_TIMEOUT_SECONDS:
                    continue  # Node marked dead/unresponsive

                # Usable memory after reserving 512 MB for host OS
                usable_ram = node.free_ram_mb - HOST_RESERVED_RAM_MB
                if usable_ram >= required_ram_mb:
                    healthy_candidates.append(node)

            if not healthy_candidates:
                raise InsufficientCapacityError(
                    f"No node has sufficient free RAM ({required_ram_mb} MB requested with {HOST_RESERVED_RAM_MB} MB reserved)."
                )

            # Sort descending by free_ram_mb: pick the node with the most headroom
            healthy_candidates.sort(key=lambda n: n.free_ram_mb, reverse=True)
            return healthy_candidates[0]