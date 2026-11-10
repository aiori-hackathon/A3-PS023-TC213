import subprocess
import logging
import hashlib
import os
from typing import Tuple

logger = logging.getLogger("worker_network")
BRIDGE_NAME = os.getenv("CH_BRIDGE", "ch-br0")

def generate_mac_and_ip(vm_id: str) -> Tuple[str, str]:
    """Generates a deterministic MAC and IP address based on VM ID."""
    h = hashlib.sha256(vm_id.encode()).hexdigest()
    # Locally administered unicast MAC: 02:XX:XX:XX:XX:XX
    mac = f"02:{h[0:2]}:{h[2:4]}:{h[4:6]}:{h[6:8]}:{h[8:10]}"
    # Deterministic IP in 172.20.0.2 - 172.20.0.254 range
    ip_suffix = (int(h[10:14], 16) % 250) + 2
    ip = f"172.20.0.{ip_suffix}"
    return mac, ip

def create_tap_device(vm_id: str) -> str:
    """Creates a dedicated TAP device, binds it to ch-br0, and brings it up."""
    # Interface name must be <= 15 chars in Linux
    tap_name = f"tap-{vm_id[:8]}"
    try:
        # Purge dangling device if it exists
        subprocess.run(["sudo", "ip", "link", "del", tap_name], stderr=subprocess.DEVNULL)
        
        # Create TAP
        subprocess.run(["sudo", "ip", "tuntap", "add", "dev", tap_name, "mode", "tap"], check=True)
        # Bind to bridge
        subprocess.run(["sudo", "ip", "link", "set", "dev", tap_name, "master", BRIDGE_NAME], check=True)
        # Bring interface up
        subprocess.run(["sudo", "ip", "link", "set", "dev", tap_name, "up"], check=True)
        
        logger.info(f"Created and bound TAP device {tap_name} to {BRIDGE_NAME}")
        return tap_name
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed creating TAP device {tap_name}: {e}")
        return ""

def destroy_tap_device(vm_id: str):
    """Destroys the VM TAP device."""
    tap_name = f"tap-{vm_id[:8]}"
    try:
        subprocess.run(["sudo", "ip", "link", "del", tap_name], check=True, stderr=subprocess.DEVNULL)
        logger.info(f"Destroyed TAP device {tap_name}")
    except subprocess.CalledProcessError:
        pass
