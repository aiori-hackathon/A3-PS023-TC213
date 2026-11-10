# AIORI Hackathon 3 — Team Episteme A3-PS023-TC213

## Problem Statement: PS-023 — Minimal Two-Node Cloud Hypervisor VM Controller

An authenticated, deterministic, and leak-free micro-cloud control plane managing Cloud Hypervisor virtual machines across two independent KVM worker hosts.

---

## Release v2.0 Overview & Core Milestones

Release `v2.0` elevates the control plane from a prototype scheduler into an enterprise-ready, fault-tolerant virtualization orchestrator:

* **Production Virtual Networking (Phase 1):** Deterministic MAC/IP allocation, dedicated per-VM TAP interfaces (`tap-vm-<id>`) attached to bridge `ch-br0`, and outbound egress masquerade NAT via `iptables`.
* **Copy-on-Write Thin Provisioning (Phase 2):** Instantaneous sub-second disk provisioning using QCOW2 overlays linked to immutable golden base images (`rootfs.qcow2`), reducing disk overhead from gigabytes to ~196 KB per instance.
* **Persistent Cluster Store & HA Reconciler (Phase 3):** SQLite in Write-Ahead Logging (WAL) mode for atomic, ACID-compliant cluster topology tracking. Background reconciler detects dead node heartbeats (>10s) and triggers automated VM eviction and failover rescheduling.
* **Prometheus Observability Exporter (Phase 4):** Standard `/api/v1/metrics` exposition endpoint emitting gauges for node health status, allocated vs. total RAM headroom, allocated vCPUs, and cluster-wide VM state metrics.
* **Unified Management CLI (`chctl`) & Operations Dashboard (Phase 5):** Comprehensive CLI tool for orchestrating nodes, microVM lifecycles, and telemetry, complemented by a zero-leak residual auditor and dark-mode operations console.
* **100% Automated Test Coverage:** 17/17 integration and unit tests passing cleanly with zero process or socket leaks.

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

```text
                               +-------------------------------------------------+
                               |    Cluster Controller (FastAPI on Port 8000)    |
                               |  - SQLite (WAL Mode) State Store                |
                               |  - Constant-Time Bearer Auth (Admin & Worker)   |
                               |  - Dynamic Headroom Placement Scheduler        |
                               |  - Background HA Reconciler (Failover Loop)     |
                               |  - Prometheus Metrics Exporter (/metrics)       |
                               |  - Web Operations Console (/dashboard)          |
                               +-----------------------+-------------------------+
                                                       |
                             +-------------------------+-------------------------+
                             | (HTTP RPC with X-Worker-Token)                   | (HTTP RPC with X-Worker-Token)
                             v                                                   v
           +-----------------------------------+               +-----------------------------------+
           |    Worker Node 1 (Port 8001)      |               |    Worker Node 2 (Port 8002)      |
           | - Heartbeat Telemetry Loop        |               | - Heartbeat Telemetry Loop        |
           | - TAP & Bridge (ch-br0) NAT Net   |               | - TAP & Bridge (ch-br0) NAT Net   |
           | - QCOW2 CoW Overlay Generator     |               | - QCOW2 CoW Overlay Generator     |
           | - HTTP-over-UDS REST Driver       |               | - HTTP-over-UDS REST Driver       |
           | - cgroups v2 Quota Containment    |               | - cgroups v2 Quota Containment    |
           +-----------------+-----------------+               +-----------------+-----------------+
                             |                                                   |
                   +---------+---------+                               +---------+---------+
                   |                   |                               |                   |
                   v                   v                               v                   v
           [Cloud Hypervisor]  [Cloud Hypervisor]              [Cloud Hypervisor]  [Cloud Hypervisor]
              (MicroVM 1)         (MicroVM 2)                     (MicroVM 3)         (MicroVM 4)

```

### Component Breakdown

* **Central Controller (Port: 8000)**
* Manages global VM placement and cluster metadata state via persistent SQLite with WAL mode.
* Continuously evaluates compute node health, heartbeats, and memory headroom.
* Routes provisioning actions directly to the chosen worker node over authenticated HTTP RPC.
* Runs a background high-availability (HA) reconciler loop that detects node failures and reschedules orphaned workloads.
* Exposes Prometheus text-format metrics at `/api/v1/metrics`.


* **Worker Node 1 (Port: 8001)**
* Emits continuous telemetry heartbeats (total and free RAM) to the Central Controller.
* Configures virtual networking: provisions host TAP interfaces, dynamically computes unique MAC/IP addresses, binds interfaces to `ch-br0`, and programs iptables egress masquerade rules.
* Generates per-instance QCOW2 overlays against immutable backing files via `qemu-img`.
* Manages dedicated Cloud Hypervisor instances via Unix Domain Sockets (`/tmp/ch_sockets/`).
* Enforces process lifecycle execution (`create`, `boot`, `shutdown`, `destroy`).


* **Worker Node 2 (Port: 8002)**
* Operates symmetrically with Worker Node 1 across an independent host environment.
* Hosts guest virtual machines scheduled based on real-time memory availability.
* Provides complete fault and execution isolation for provisioned workloads.



### Core Design Highlights

1. **Direct Unix Domain Socket Control:** Eliminates shell injection vulnerabilities; all commands interact with Cloud Hypervisor's native REST API (`/api/v1/vm.create`, `/api/v1/vm.boot`, `/api/v1/vm.shutdown`, `/api/v1/vmm.shutdown`) via raw HTTP-over-UDS transport.
2. **Deterministic Virtual Networking:** TAP interfaces (`tap-vm-<id>`) bound to bridge `ch-br0` with deterministic MAC generation (`02:xx:xx:...`) and subnet IP reservation (`172.20.0.0/16`), allowing outbound Internet connectivity via kernel masquerade NAT.
3. **CoW Thin Provisioning:** Each microVM receives a lightweight QCOW2 delta overlay linked to a shared read-only golden base image (`rootfs.qcow2`), enabling sub-second spin-up times.
4. **512 MB OS Memory Reservation:** The placement engine strictly preserves a baseline 512 MB memory cushion on each node to ensure host operating system stability and kernel health.
5. **Dynamic Scheduling & Telemetry:** Worker heartbeats track real-time host RAM capacity; provisioning requests are placed onto the node with optimal headroom.
6. **Constant-Time Cryptographic Auth:** Controller client endpoints and inter-worker communication are guarded by Bearer tokens and `X-Worker-Token` headers evaluated with `secrets.compare_digest`.
7. **Concurrency Safety & ACID State:** SQLite with Write-Ahead Logging (WAL) handles concurrent state queries, and controller placement calculations are serialized to prevent overcommit race conditions.
8. **Automated Zero-Leak Enforcement:** Every shutdown or delete call destroys TAP devices, deletes disk overlays, purges Unix domain sockets, and terminates dangling hypervisor processes.

---

## Repository Structure

```text
.
├── Makefile                          # Unified build, test, demo, and audit runner
├── chctl                             # Executable command-line cluster control client
├── controller/
│   ├── audit.py                      # Append-only JSON audit logging engine
│   ├── db.py                         # SQLite WAL persistence layer & ClusterStore
│   ├── metrics.py                    # Prometheus exposition metrics generator
│   ├── reconciler.py                 # Cluster HA reconciler & automated failover loop
│   ├── security.py                   # Constant-time token verification & auth schemes
│   ├── server.py                     # Central FastAPI controller & scheduling endpoints
│   └── templates/
│       └── dashboard.html            # Production operations console (Tailored UI)
├── worker/
│   ├── agent.py                      # Node worker daemon & VMM lifecycle manager
│   ├── capabilities.py               # Hardware KVM & virtio feature detection
│   ├── network.py                    # TAP device creation, bridge bonding & NAT rules
│   └── storage.py                    # QCOW2 Copy-on-Write overlay provisioning
├── deploy/
│   └── systemd/                      # Production systemd unit service templates
│       ├── ch-controller.service
│       └── ch-worker.service
├── scripts/
│   ├── fetch_artifacts.sh            # Downloads kernel and golden rootfs images
│   ├── leak_check.sh                 # Zero-leak audit checking sockets and processes
│   ├── provision_vm.sh               # Shell script for manual VM provisioning test
│   ├── run_cluster.sh                # Boots controller and two worker nodes
│   ├── run_demo.sh                   # Comprehensive 8-step end-to-end evaluation runner
│   └── start_cluster.sh              # Background cluster initialization helper
└── tests/                            # Automated test suite (17 comprehensive test cases)
    ├── conftest.py                   # Clean test state fixture hook
    ├── test_ch_client.py
    ├── test_e2e_flow.py
    ├── test_lifecycle_state_machine.py
    ├── test_multinode_integration.py
    ├── test_reconciler_and_cleanup.py
    ├── test_scheduler.py
    ├── test_security_and_limits.py
    ├── test_store.py
    └── test_worker_agent.py

```

---

## Quickstart & Verification

### 1. Setup Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

```

### 2. Fetch Hypervisor Kernel & Rootfs Artifacts

```bash
./scripts/fetch_artifacts.sh

```

### 3. Run Complete Automated Test Suite (17 Tests)

```bash
make test
# or
pytest -v

```

### 4. Run the Full End-to-End Evaluation Demo

Executes the automated 8-step evaluation pipeline (node discovery, security rejections, resource guardrails, dynamic placement, lifecycle state machine, and zero-leak audit):

```bash
make demo
# or
./scripts/run_demo.sh

```

### 5. Run the Zero-Leak Residual Auditor

Inspects `/tmp/ch_sockets` and process table to verify zero dangling sockets, overlays, or orphaned processes:

```bash
make audit
# or
./scripts/leak_check.sh

```

---

## CLI Management Tool (`chctl`)

The project includes `chctl`, a standalone CLI utility for cluster operations:

### Discover Cluster Nodes

```bash
./chctl nodes list

```

### Provision a MicroVM

```bash
./chctl vm spawn --name prod-workload-01 --vcpus 2 --memory 1024

```

### List Tracked VMs

```bash
./chctl vm list

```

### VM Lifecycle Operations

```bash
# Stop VM
./chctl vm stop <VM_ID>

# Start VM
./chctl vm start <VM_ID>

# Terminate & Deprovision VM
./chctl vm delete <VM_ID>

```

### Live Prometheus Telemetry via CLI

```bash
./chctl metrics

```

---

## Web Operations Console

The controller serves a dark-mode operations console at `http://localhost:8000/` or `http://localhost:8000/dashboard`:

* **Live Node Telemetry:** Real-time RAM utilization meters, allocated vs. free headroom, and KVM acceleration badges.


* **MicroVM Inventory:** Real-time table displaying VM ID, placement node, vCPUs, RAM, and network metadata (IP/MAC).
* **Inline Lifecycle Management:** Interactive **Start**, **Stop**, and **Delete** actions triggering instant backend state transitions.
* **Integrated API Token Management:** Securely passes Bearer authentication headers directly to the controller REST endpoints.

---

## Prometheus Telemetry Exposition

Live telemetry is exposed at `http://localhost:8000/api/v1/metrics`:

* `ch_cluster_node_status`: Binary gauge indicating worker node reachability (1 = ONLINE, 0 = OFFLINE).
* `ch_cluster_node_ram_total_mb`: Total capacity per node.
* `ch_cluster_node_ram_free_mb`: Available allocatable memory headroom.
* `ch_cluster_vms_total`: Total microVMs tracked in cluster state.
* `ch_cluster_vm_vcpu_allocated`: Allocated vCPUs per microVM instance.
* `ch_cluster_vm_memory_mb_allocated`: Allocated memory in megabytes per microVM instance.

---

## Security Model & Guardrails

* **Constant-Time Verification:** Tokens are verified using `secrets.compare_digest` to prevent timing attacks.
* **Separation of Concerns:** Client requests require `CONTROLLER_API_KEY` (`Authorization: Bearer <token>`). Inter-node worker RPCs require `WORKER_SHARED_SECRET` (`X-Worker-Token: <token>`).
* **Resource Limit Guardrails:** Strict Pydantic validators reject requests requesting more than 4 vCPUs or 2048 MB RAM with `HTTP 422 Unprocessable Entity`.
* **State Machine Protection:** Conflict prevention returns `HTTP 409 Conflict` on illegal state transitions (e.g., attempting to start an already running VM or stopping a stopped VM).
