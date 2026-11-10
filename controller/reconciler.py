import asyncio
import logging
from datetime import datetime, timezone
import httpx
from controller.db import store

logger = logging.getLogger("controller_ha")
HEARTBEAT_TIMEOUT_SECONDS = 10.0
WORKER_SHARED_SECRET = "default-worker-secret"

async def evict_and_reschedule_vm(vm: dict, dead_node_id: str):
    logger.warning(f"HA: Evicting VM {vm['vm_id']} from dead node {dead_node_id}")
    
    nodes = [n for n in store.get_all_nodes() if n["health_status"] == "ONLINE" and n["node_id"] != dead_node_id]
    eligible = [n for n in nodes if n["free_ram_mb"] >= vm["memory_mb"]]
    if not eligible:
        logger.error(f"HA: Cannot failover VM {vm['vm_id']}: No eligible healthy node found.")
        vm["status"] = "ERROR_FAILOVER_NO_CAPACITY"
        store.upsert_vm(vm)
        return

    target_node = max(eligible, key=lambda n: n["free_ram_mb"])
    target_url = f"http://{target_node['host']}:{target_node['port']}"

    headers = {"X-Worker-Token": WORKER_SHARED_SECRET}
    payload = {
        "vm_id": vm["vm_id"],
        "name": vm["name"],
        "vcpus": vm["vcpus"],
        "memory_mb": vm["memory_mb"]
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{target_url}/api/v1/vms/spawn", json=payload, headers=headers)
            if resp.status_code == 201:
                data = resp.json()
                vm["node_id"] = target_node["node_id"]
                vm["status"] = "RUNNING"
                vm["ip"] = data.get("ip")
                vm["mac"] = data.get("mac")
                store.upsert_vm(vm)
                logger.info(f"HA: VM {vm['vm_id']} successfully failed over to {target_node['node_id']}.")
            else:
                logger.error(f"HA: Failed spawning VM on {target_node['node_id']}: {resp.text}")
    except Exception as e:
        logger.error(f"HA: Network error migrating VM {vm['vm_id']} to {target_node['node_id']}: {e}")

async def cluster_ha_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            nodes = store.get_all_nodes()
            for node in nodes:
                try:
                    last_hb = datetime.fromisoformat(node["last_heartbeat"])
                    delta = (now - last_hb).total_seconds()
                    
                    if delta > HEARTBEAT_TIMEOUT_SECONDS and node["health_status"] == "ONLINE":
                        logger.error(f"HA: Node {node['node_id']} heartbeat missed ({delta:.1f}s ago). Marking OFFLINE.")
                        store.set_node_health(node["node_id"], "OFFLINE")
                        
                        orphaned_vms = store.get_vms_by_node(node["node_id"])
                        for vm in orphaned_vms:
                            if vm["status"] == "RUNNING":
                                asyncio.create_task(evict_and_reschedule_vm(vm, node["node_id"]))
                except Exception as ex:
                    logger.error(f"Error checking node {node.get('node_id')}: {ex}")
        except Exception as e:
            logger.error(f"HA loop exception: {e}")

        await asyncio.sleep(2)
