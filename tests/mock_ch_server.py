import os
import asyncio
from typing import Dict, Any
from fastapi import FastAPI, Response, status
import uvicorn

def create_mock_ch_app() -> FastAPI:
    """Mock Cloud Hypervisor REST API over Unix Domain Socket."""
    app = FastAPI(title="MockCloudHypervisor")
    state: Dict[str, Any] = {
        "status": "Created",
        "config": {},
        "booted": False,
    }

    @app.get("/api/v1/vmm.ping")
    def vmm_ping():
        return Response(status_code=status.HTTP_200_OK)

    @app.put("/api/v1/vm.create")
    def vm_create(config: Dict[str, Any]):
        state["config"] = config
        state["status"] = "Created"
        return Response(status_code=status.HTTP_200_OK, content='{"status":"created"}', media_type="application/json")

    @app.put("/api/v1/vm.boot")
    def vm_boot():
        state["booted"] = True
        state["status"] = "Running"
        return Response(status_code=status.HTTP_200_OK, content='{"status":"booted"}', media_type="application/json")

    @app.get("/api/v1/vm.info")
    def vm_info():
        return {
            "config": state["config"],
            "state": state["status"],
            "memory_actual": state["config"].get("memory", {}).get("size", 536870912),
        }

    @app.put("/api/v1/vm.shutdown")
    def vm_shutdown():
        state["status"] = "Shutdown"
        state["booted"] = False
        return Response(status_code=status.HTTP_200_OK)

    @app.put("/api/v1/vmm.shutdown")
    def vmm_shutdown():
        return Response(status_code=status.HTTP_200_OK)

    return app