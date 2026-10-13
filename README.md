# AIORI Hackathon 3 — Team Episteme A3-PS023-TC213

## Problem Statement: PS-023 — Minimal Two-Node Cloud Hypervisor VM Controller

An authenticated, deterministic, and leak-free micro-cloud control plane managing Cloud Hypervisor virtual machines across two independent KVM worker hosts.

---

## 📺 Team Introduction & Orientation Video
Watch our introductory walkthrough explaining our team roles, problem breakdown, and proposed system architecture:

- **YouTube Link:** https://www.youtube.com/watch?v=

---

## 👥 Team Composition & Work Areas

| Name | Role | Responsibilities / Work Areas |
| :--- | :--- | :--- |
| **Soham Chakraborti** | Team Lead & Systems Engineer | • Linux KVM (`/dev/kvm`) and Cloud Hypervisor binary management.<br>• IPC over Cloud Hypervisor REST API via Unix domain sockets.<br>• Controller placement algorithm and host OS memory reservations.<br>• Lifecycle state machine transitions (`CREATING` → `CREATED` → `RUNNING` → `STOPPED` → `DELETED`). |
| **Ishita Roy** | Reliability, Security & QA Engineer | • Process containment using Linux cgroups v2 (`MemoryMax`, `CPUQuota`).<br>• Self-healing background Reconciler for cleaning orphan PIDs, taps, and sockets.<br>• Bearer token authentication and controller-to-worker secure channels.<br>• Failure injection testing and automated `leak_check.sh` verification. |
| **Sayani Manna** | Faculty Mentor | • Project oversight, RFC alignment, and academic advisory. |

---

## 📄 Orientation Slide Deck
The 11-slide presentation adhering to the official AIORI template is included in this repository:
- **Presentation Path:** /A3-PS023-TC213_AIORI3_Presentation.pdf

---
