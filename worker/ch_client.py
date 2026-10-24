import json
import logging
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger("ch_client")

class CloudHypervisorClient:
    """
    Communicates with Cloud Hypervisor's REST API over a Unix Domain Socket.
    Uses httpx.HTTPTransport with uds (Unix Domain Socket) path.
    """
    def __init__(self, socket_path: str, timeout: float = 10.0):
        self.socket_path = socket_path
        self.timeout = timeout
        # Cloud Hypervisor listens on a local Unix socket. The host in the URL is dummy 'localhost'.
        self.transport = httpx.HTTPTransport(uds=self.socket_path)
        self.base_url = "http://localhost/api/v1"

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=self.timeout)

    def ping(self) -> bool:
        """vmm.ping: checks if the VMM process API is alive and responsive."""
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/vmm.ping")
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Ping failed on {self.socket_path}: {e}")
            return False

    def create_vm(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """vm.create: configures vCPUs, memory, kernel/firmware, disks, and network interfaces."""
        with self._client() as client:
            res = client.put(f"{self.base_url}/vm.create", json=config)
            if res.status_code not in (200, 204):
                raise RuntimeError(f"vm.create failed ({res.status_code}): {res.text}")
            return res.json() if res.text else {"status": "created"}

    def boot_vm(self) -> Dict[str, Any]:
        """vm.boot: boots the configured VM into execution."""
        with self._client() as client:
            res = client.put(f"{self.base_url}/vm.boot")
            if res.status_code not in (200, 204):
                raise RuntimeError(f"vm.boot failed ({res.status_code}): {res.text}")
            return res.json() if res.text else {"status": "booted"}

    def get_info(self) -> Dict[str, Any]:
        """vm.info: retrieves running state, memory footprint, and device data."""
        with self._client() as client:
            res = client.get(f"{self.base_url}/vm.info")
            if res.status_code != 200:
                raise RuntimeError(f"vm.info failed ({res.status_code}): {res.text}")
            return res.json()

    def shutdown_vm(self) -> bool:
        """vm.shutdown: sends ACPI power button event for graceful guest shutdown."""
        with self._client() as client:
            res = client.put(f"{self.base_url}/vm.shutdown")
            return res.status_code in (200, 204)

    def shutdown_vmm(self) -> bool:
        """vmm.shutdown: instructs the Cloud Hypervisor process to exit cleanly."""
        try:
            with self._client() as client:
                res = client.put(f"{self.base_url}/vmm.shutdown")
                return res.status_code in (200, 204)
        except (httpx.RemoteProtocolError, httpx.ConnectError):
            # The process exits immediately upon vmm.shutdown, closing the socket
            return True