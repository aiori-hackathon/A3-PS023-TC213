import asyncio
from datetime import datetime, timezone
from typing import Optional
from controller.store import MetadataStore
from controller.models import NodeRecord

HOST_RESERVED_RAM_MB = 512
HEARTBEAT_TIMEOUT_SECONDS = 10.0

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
        Filters for ONLINE nodes, verifies memory headroom above the host reserve,
        and selects the node with the highest available capacity.
        """
        async with self._lock:
            nodes = self.store.list_nodes()
            if not nodes:
                raise NoHealthyNodesError("No compute nodes registered in the cluster.")

            now = datetime.now(timezone.utc)
            healthy_nodes = []

            for node in nodes:
                # 1. Skip inactive nodes
                if hasattr(node, "is_active") and not node.is_active:
                    continue

                # 2. Check health status using model computation or heartbeat age
                if hasattr(node, "health_status"):
                    if node.health_status != "ONLINE":
                        continue
                else:
                    node_hb = node.last_heartbeat
                    if node_hb.tzinfo is None:
                        node_hb = node_hb.replace(tzinfo=timezone.utc)
                    if (now - node_hb).total_seconds() > HEARTBEAT_TIMEOUT_SECONDS:
                        continue

                healthy_nodes.append(node)

            if not healthy_nodes:
                raise NoHealthyNodesError("No online and healthy compute nodes available in the cluster.")

            # Filter candidates that satisfy the required memory above host reserve
            eligible_candidates = [
                n for n in healthy_nodes
                if (n.free_ram_mb - HOST_RESERVED_RAM_MB) >= required_ram_mb
            ]

            if not eligible_candidates:
                raise InsufficientCapacityError(
                    f"No node has sufficient free RAM ({required_ram_mb} MB requested with {HOST_RESERVED_RAM_MB} MB reserved)."
                )

            # Sort descending by free_ram_mb: pick the node with the most headroom
            eligible_candidates.sort(key=lambda n: n.free_ram_mb, reverse=True)
            return eligible_candidates[0]