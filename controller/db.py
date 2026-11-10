import sqlite3
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

DEFAULT_DB_PATH = os.getenv("CONTROLLER_DB_PATH", "data/cluster_state.db")

class ClusterStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._init_db()

    @property
    def db_path(self) -> str:
        return self._db_path

    @db_path.setter
    def db_path(self, val: str):
        self._db_path = val
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        conn.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            total_ram_mb INTEGER NOT NULL,
            free_ram_mb INTEGER NOT NULL,
            kvm_capable BOOLEAN DEFAULT 1,
            runtime_driver TEXT DEFAULT 'kvm',
            health_status TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS vms (
            vm_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            vcpus INTEGER NOT NULL,
            memory_mb INTEGER NOT NULL,
            node_id TEXT,
            status TEXT NOT NULL,
            ip TEXT,
            mac TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES nodes (node_id)
        );
        """)
        conn.commit()
        return conn

    def _init_db(self):
        with self.get_connection():
            pass

    def upsert_node(self, data: Dict[str, Any]):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO nodes (node_id, host, port, total_ram_mb, free_ram_mb, kvm_capable, runtime_driver, health_status, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                host=excluded.host,
                port=excluded.port,
                total_ram_mb=excluded.total_ram_mb,
                free_ram_mb=excluded.free_ram_mb,
                kvm_capable=excluded.kvm_capable,
                runtime_driver=excluded.runtime_driver,
                health_status=excluded.health_status,
                last_heartbeat=excluded.last_heartbeat;
            """, (
                data["node_id"], data["host"], data["port"],
                data["total_ram_mb"], data["free_ram_mb"],
                data.get("kvm_capable", True), data.get("runtime_driver", "kvm"),
                data.get("health_status", "ONLINE"),
                data.get("last_heartbeat", datetime.now(timezone.utc).isoformat())
            ))
            conn.commit()

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
            return [dict(r) for r in rows]

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
            return dict(row) if row else None

    def set_node_health(self, node_id: str, status: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE nodes SET health_status = ? WHERE node_id = ?", (status, node_id))
            conn.commit()

    def upsert_vm(self, data: Dict[str, Any]):
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO vms (vm_id, name, vcpus, memory_mb, node_id, status, ip, mac, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vm_id) DO UPDATE SET
                node_id=excluded.node_id,
                status=excluded.status,
                ip=excluded.ip,
                mac=excluded.mac,
                updated_at=excluded.updated_at;
            """, (
                data["vm_id"], data["name"], data["vcpus"], data["memory_mb"],
                data.get("node_id"), data["status"], data.get("ip"), data.get("mac"),
                data.get("created_at", now), data.get("updated_at", now)
            ))
            conn.commit()

    def get_vm(self, vm_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM vms WHERE vm_id = ?", (vm_id,)).fetchone()
            return dict(row) if row else None

    def get_all_vms(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM vms WHERE status != 'DELETED'").fetchall()
            return [dict(r) for r in rows]

    def get_vms_by_node(self, node_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM vms WHERE node_id = ? AND status != 'DELETED'", (node_id,)).fetchall()
            return [dict(r) for r in rows]

    def delete_vm_record(self, vm_id: str):
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("UPDATE vms SET status = 'DELETED', updated_at = ? WHERE vm_id = ?", (now, vm_id))
            conn.commit()

    def clear(self):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM vms;")
            conn.execute("DELETE FROM nodes;")
            conn.commit()

store = ClusterStore()

# Explicit exports for direct functional imports
def get_all_nodes(): return store.get_all_nodes()
def get_node(nid): return store.get_node(nid)
def set_node_health(nid, status): return store.set_node_health(nid, status)
def upsert_node(data): return store.upsert_node(data)
def upsert_vm(data): return store.upsert_vm(data)
def get_vm(vid): return store.get_vm(vid)
def get_all_vms(): return store.get_all_vms()
def get_vms_by_node(nid): return store.get_vms_by_node(nid)
def delete_vm_record(vid): return store.delete_vm_record(vid)
