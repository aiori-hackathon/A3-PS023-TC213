import time
from typing import List
from controller.db import store

def generate_prometheus_metrics() -> str:
    """Generates Prometheus text exposition metrics for the orchestrator."""
    lines: List[str] = []

    # Node metrics
    lines.append("# HELP ch_cluster_node_status Health status of cluster nodes (1=ONLINE, 0=OFFLINE)")
    lines.append("# TYPE ch_cluster_node_status gauge")

    lines.append("# HELP ch_cluster_node_ram_total_mb Total memory capacity reported by worker in MB")
    lines.append("# TYPE ch_cluster_node_ram_total_mb gauge")

    lines.append("# HELP ch_cluster_node_ram_free_mb Free memory headroom available on worker in MB")
    lines.append("# TYPE ch_cluster_node_ram_free_mb gauge")

    nodes = store.get_all_nodes()
    for n in nodes:
        nid = n["node_id"]
        status_val = 1 if n.get("health_status") == "ONLINE" else 0
        driver = n.get("runtime_driver", "kvm")
        lines.append(f'ch_cluster_node_status{{node_id="{nid}",driver="{driver}"}} {status_val}')
        lines.append(f'ch_cluster_node_ram_total_mb{{node_id="{nid}"}} {n.get("total_ram_mb", 0)}')
        lines.append(f'ch_cluster_node_ram_free_mb{{node_id="{nid}"}} {n.get("free_ram_mb", 0)}')

    # VM metrics
    lines.append("# HELP ch_cluster_vms_total Total microVMs tracked in cluster state")
    lines.append("# TYPE ch_cluster_vms_total gauge")

    lines.append("# HELP ch_cluster_vm_vcpu_allocated Allocated vCPUs per microVM")
    lines.append("# TYPE ch_cluster_vm_vcpu_allocated gauge")

    lines.append("# HELP ch_cluster_vm_memory_mb_allocated Allocated memory in MB per microVM")
    lines.append("# TYPE ch_cluster_vm_memory_mb_allocated gauge")

    vms = store.get_all_vms()
    lines.append(f"ch_cluster_vms_total {len(vms)}")

    for vm in vms:
        vid = vm["vm_id"]
        nid = vm.get("node_id", "unassigned")
        st = vm.get("status", "UNKNOWN")
        vcpus = vm.get("vcpus", 1)
        mem = vm.get("memory_mb", 512)
        lines.append(f'ch_cluster_vm_vcpu_allocated{{vm_id="{vid}",node_id="{nid}",status="{st}"}} {vcpus}')
        lines.append(f'ch_cluster_vm_memory_mb_allocated{{vm_id="{vid}",node_id="{nid}",status="{st}"}} {mem}')

    return "\n".join(lines) + "\n"
