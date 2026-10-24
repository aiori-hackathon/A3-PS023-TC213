import os
import time
import socket
import threading
import pytest
import uvicorn
import httpx

from controller.server import app as controller_app, store
from worker.agent import app as worker_app

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

class ServerThread(threading.Thread):
    def __init__(self, app, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.server = uvicorn.Server(
            uvicorn.Config(app=app, host="127.0.0.1", port=self.port, log_level="error")
        )

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True

@pytest.fixture(scope="module")
def cluster_services():
    c_port = find_free_port()
    w1_port = find_free_port()
    w2_port = find_free_port()

    # Clear stale database
    if os.path.exists("controller.db"):
        os.remove("controller.db")
    store._init_db()

    c_server = ServerThread(controller_app, c_port)
    w1_server = ServerThread(worker_app, w1_port)
    w2_server = ServerThread(worker_app, w2_port)

    c_server.start()
    w1_server.start()
    w2_server.start()

    time.sleep(0.5)

    yield {
        "controller_url": f"http://127.0.0.1:{c_port}",
        "w1_port": w1_port,
        "w2_port": w2_port,
    }

    c_server.stop()
    w1_server.stop()
    w2_server.stop()
    if os.path.exists("controller.db"):
        os.remove("controller.db")

def test_two_node_dynamic_provisioning_and_placement(cluster_services):
    c_url = cluster_services["controller_url"]
    w1_port = cluster_services["w1_port"]
    w2_port = cluster_services["w2_port"]

    with httpx.Client(base_url=c_url, timeout=5.0) as client:
        # 1. Register Node 1: 2048 MB free
        hb1 = {
            "node_id": "node-1",
            "host": "127.0.0.1",
            "port": w1_port,
            "total_ram_mb": 4096,
            "free_ram_mb": 2048
        }
        res1 = client.post("/api/v1/nodes/heartbeat", json=hb1)
        assert res1.status_code == 200

        # 2. Register Node 2: 8192 MB free (Scheduler should select Node 2)
        hb2 = {
            "node_id": "node-2",
            "host": "127.0.0.1",
            "port": w2_port,
            "total_ram_mb": 16384,
            "free_ram_mb": 8192
        }
        res2 = client.post("/api/v1/nodes/heartbeat", json=hb2)
        assert res2.status_code == 200

        # 3. Request Controller to provision a VM (1024 MB)
        vm_payload = {
            "name": "guest-db-01",
            "vcpus": 2,
            "memory_mb": 1024
        }
        create_res = client.post("/api/v1/vms", json=vm_payload)
        assert create_res.status_code == 201
        vm_data = create_res.json()

        vm_id = vm_data["vm_id"]
        assert vm_data["status"] == "RUNNING"
        # Confirm it placed on Node 2 (the node with 8192 MB free)
        assert vm_data["node_id"] == "node-2"

        # 4. Query VM status via Controller
        status_res = client.get(f"/api/v1/vms/{vm_id}")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "RUNNING"

        # 5. Delete VM
        del_res = client.delete(f"/api/v1/vms/{vm_id}")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "TERMINATED"