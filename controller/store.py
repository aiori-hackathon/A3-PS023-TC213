import sqlite3
from datetime import datetime, timezone
from typing import List, Optional
from controller.models import NodeHeartbeat, NodeRecord, VMRecord

DB_PATH = "controller.db"

class MetadataStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    total_ram_mb INTEGER NOT NULL,
                    free_ram_mb INTEGER NOT NULL,
                    last_heartbeat TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vms (
                    vm_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    vcpus INTEGER NOT NULL,
                    memory_mb INTEGER NOT NULL,
                    node_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                )
            """)
            conn.commit()

    def upsert_node(self, hb: NodeHeartbeat) -> None:
        self._init_db()  # Ensures tables exist even if the db file was recreated
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO nodes (node_id, host, port, total_ram_mb, free_ram_mb, last_heartbeat, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(node_id) DO UPDATE SET
                    host=excluded.host,
                    port=excluded.port,
                    total_ram_mb=excluded.total_ram_mb,
                    free_ram_mb=excluded.free_ram_mb,
                    last_heartbeat=excluded.last_heartbeat,
                    is_active=1
            """, (hb.node_id, hb.host, hb.port, hb.total_ram_mb, hb.free_ram_mb, now))
            conn.commit()

    def list_nodes(self) -> List[NodeRecord]:
        self._init_db()
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM nodes WHERE is_active = 1").fetchall()
            return [
                NodeRecord(
                    node_id=row["node_id"],
                    host=row["host"],
                    port=row["port"],
                    total_ram_mb=row["total_ram_mb"],
                    free_ram_mb=row["free_ram_mb"],
                    last_heartbeat=datetime.fromisoformat(row["last_heartbeat"]),
                    is_active=bool(row["is_active"])
                )
                for row in rows
            ]

    def insert_vm(self, vm: VMRecord) -> None:
        self._init_db()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO vms (vm_id, name, vcpus, memory_mb, node_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                vm.vm_id,
                vm.name,
                vm.vcpus,
                vm.memory_mb,
                vm.node_id,
                vm.status,
                vm.created_at.isoformat(),
                vm.updated_at.isoformat()
            ))
            conn.commit()

    def update_vm_status(self, vm_id: str, status: str, node_id: Optional[str] = None) -> None:
        self._init_db()
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            if node_id:
                conn.execute(
                    "UPDATE vms SET status = ?, node_id = ?, updated_at = ? WHERE vm_id = ?",
                    (status, node_id, now, vm_id)
                )
            else:
                conn.execute(
                    "UPDATE vms SET status = ?, updated_at = ? WHERE vm_id = ?",
                    (status, now, vm_id)
                )
            conn.commit()

    def get_vm(self, vm_id: str) -> Optional[VMRecord]:
        self._init_db()
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM vms WHERE vm_id = ?", (vm_id,)).fetchone()
            if not row:
                return None
            return VMRecord(
                vm_id=row["vm_id"],
                name=row["name"],
                vcpus=row["vcpus"],
                memory_mb=row["memory_mb"],
                node_id=row["node_id"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )