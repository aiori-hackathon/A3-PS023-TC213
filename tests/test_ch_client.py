import os
import time
import threading
import pytest
import uvicorn
from worker.ch_client import CloudHypervisorClient
from tests.mock_ch_server import create_mock_ch_app

TEST_SOCKET = "/tmp/test_ch.sock"

@pytest.fixture(scope="module", autouse=True)
def run_mock_server():
    if os.path.exists(TEST_SOCKET):
        os.remove(TEST_SOCKET)

    app = create_mock_ch_app()
    server_config = uvicorn.Config(app=app, uds=TEST_SOCKET, log_level="error")
    server = uvicorn.Server(server_config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the Unix domain socket to bind
    for _ in range(50):
        if os.path.exists(TEST_SOCKET):
            break
        time.sleep(0.05)

    yield

    # Cleanup socket after tests
    if os.path.exists(TEST_SOCKET):
        os.remove(TEST_SOCKET)

def test_ch_client_full_lifecycle():
    client = CloudHypervisorClient(socket_path=TEST_SOCKET)

    # 1. Ping
    assert client.ping() is True

    # 2. vm.create
    vm_config = {
        "cpus": {"boot_vcpus": 1, "max_vcpus": 1},
        "memory": {"size": 536870912},
    }
    create_res = client.create_vm(vm_config)
    assert create_res.get("status") == "created"

    # 3. vm.boot
    boot_res = client.boot_vm()
    assert boot_res.get("status") == "booted"

    # 4. vm.info
    info = client.get_info()
    assert info["state"] == "Running"
    assert info["memory_actual"] == 536870912

    # 5. vm.shutdown
    assert client.shutdown_vm() is True

    # 6. vmm.shutdown
    assert client.shutdown_vmm() is True