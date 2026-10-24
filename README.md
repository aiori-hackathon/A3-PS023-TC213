# AIORI Hackathon 3 — Team Episteme A3-PS023-TC213

## Problem Statement: PS-023 — Minimal Two-Node Cloud Hypervisor VM Controller

An authenticated, deterministic, and leak-free micro-cloud control plane managing Cloud Hypervisor virtual machines across two independent KVM worker hosts.

---

## Team Introduction & Orientation Video
Watch our introductory walkthrough explaining our team roles, problem breakdown, and proposed system architecture:

- YouTube Link: https://www.youtube.com/watch?v=O-e3twW4i9E

---

## Team Composition & Work Areas

| Name | Role | Responsibilities / Work Areas |
| :--- | :--- | :--- |
| Soham Chakraborti | Team Lead & Systems Engineer | • Linux KVM (/dev/kvm) and Cloud Hypervisor binary management.<br>• IPC over Cloud Hypervisor REST API via Unix domain sockets.<br>• Controller placement algorithm and host OS memory reservations.<br>• Lifecycle state machine transitions (CREATING -> CREATED -> RUNNING -> STOPPED -> DELETED). |
| Ishita Roy | Reliability, Security & QA Engineer | • Process containment using Linux cgroups v2 (MemoryMax, CPUQuota).<br>• Self-healing background Reconciler for cleaning orphan PIDs, taps, and sockets.<br>• Bearer token authentication and controller-to-worker secure channels.<br>• Failure injection testing and automated leak_check.sh verification. |
| Sayani Manna | Faculty Mentor | • Project oversight, RFC alignment, and academic advisory. |

---

## Orientation Slide Deck
The 11-slide presentation adhering to the official AIORI template is included in this repository:
- Presentation Path: /A3-PS023-TC213_AIORI3_Presentation.pdf

---

## System Architecture

* **Central Controller (Port: 8000)**
  * Manages global VM placement and cluster metadata state via SQLite.
  * Continuously evaluates compute node health and memory headroom.
  * Routes provisioning actions directly to the chosen worker node over HTTP RPC.

* **Worker Node 1 (Port: 8001)**
  * Emits continuous telemetry heartbeats (total and free RAM) to the Central Controller.
  * Manages dedicated Cloud Hypervisor instances via Unix Domain Sockets (`/tmp/ch_sockets/`).
  * Enforces process lifecycle execution (`create`, `boot`, `shutdown`, `destroy`).

* **Worker Node 2 (Port: 8002)**
  * Operates symmetrically with Worker Node 1 across an independent host environment.
  * Hosts guest virtual machines scheduled based on real-time memory availability.
  * Provides complete fault and execution isolation for provisioned workloads.

### Core Design Highlights
1. **Direct Unix Domain Socket Control:** Eliminates shell injection vulnerabilities; all commands interact with Cloud Hypervisor's native REST API (`/api/v1/vm.create`, `/api/v1/vm.boot`, `/api/v1/vm.shutdown`, `/api/v1/vmm.shutdown`) via raw HTTP-over-UDS transport.
2. **512 MB OS Memory Reservation:** The placement engine strictly preserves a baseline 512 MB memory cushion on each node to ensure host operating system stability and kernel health.
3. **Dynamic Scheduling & Telemetry:** Worker heartbeats track real-time host RAM capacity; provisioning requests are placed onto the node with optimal headroom.
4. **Concurrency Safety:** Controller placement calculations are protected by an asynchronous lock to prevent overcommit race conditions.
5. **Local Verification & Multi-Environment Ready:** Designed with high-fidelity mock fallbacks for rapid local automated testing while fully functional on dual bare-metal/cloud KVM hosts.

---
## Repository Structure

- controller/: Central scheduling engine, FastAPI endpoints, Pydantic schemas, and SQLite state store.
- worker/: Node-level daemon, Cloud Hypervisor Unix Domain Socket REST driver, and lifecycle process manager.
- scripts/: Automation scripts for launching the local multi-node cluster and running end-to-end VM provisioning tests.
- tests/: Automated test suites verifying socket clients, SQLite transactions, scheduler reservations, worker lifespans, and multi-node dynamic placement.

---

## Quickstart & Verification

### 1. Setup Virtual Environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

### 2. Run Complete Automated Test Suite
pytest -v

### 3. Start the Multi-Node Cluster
./scripts/run_cluster.sh

### 4. Provision and Test an End-to-End VM Lifecycle
In a separate terminal:
./scripts/provision_vm.sh