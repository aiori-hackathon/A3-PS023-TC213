import os
import shutil
from typing import Dict, Any

def check_kvm_support() -> bool:
    """Checks if /dev/kvm exists and is readable and writable."""
    kvm_path = "/dev/kvm"
    if os.path.exists(kvm_path):
        return os.access(kvm_path, os.R_OK | os.W_OK)
    return False

def check_cpu_virtualization() -> bool:
    """Scans /proc/cpuinfo for Intel VMX or AMD SVM flags."""
    cpuinfo_path = "/proc/cpuinfo"
    if not os.path.exists(cpuinfo_path):
        return False
    try:
        with open(cpuinfo_path, "r", encoding="utf-8") as f:
            content = f.read()
            return "vmx" in content or "svm" in content
    except Exception:
        return False

def check_cloud_hypervisor_binary() -> bool:
    """Checks if the cloud-hypervisor executable is present in PATH."""
    ch_binary = os.getenv("CH_BINARY", "cloud-hypervisor")
    return shutil.which(ch_binary) is not None

def probe_node_capabilities() -> Dict[str, Any]:
    """
    Returns the node virtualization profile.
    Decides between 'kvm' and 'mock_sandbox' runtime driver.
    """
    kvm_avail = check_kvm_support()
    cpu_virt = check_cpu_virtualization()
    ch_bin = check_cloud_hypervisor_binary()

    # Hardware acceleration requires /dev/kvm access and the hypervisor binary
    is_accelerated = kvm_avail and ch_bin

    return {
        "kvm_capable": is_accelerated,
        "cpu_virtualization": cpu_virt,
        "ch_binary_found": ch_bin,
        "runtime_driver": "kvm" if is_accelerated else "mock_sandbox"
    }

if __name__ == "__main__":
    import json
    print(json.dumps(probe_node_capabilities(), indent=2))
