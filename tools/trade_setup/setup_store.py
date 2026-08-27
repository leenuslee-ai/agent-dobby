"""SQLite-backed store for trading setup definitions.

Setups are stored as JSON in a local SQLite database so they can be created,
queried, and run dynamically without any code changes.

Usage:
    from backtest.setup_store import SetupStore
    store = SetupStore()
    store.save(name="My Setup", description="...", definition={...})
    setup_dict = store.get("My Setup")
    all_setups = store.list()
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path("./backtest_cache/setups.db")


class SetupStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(exist_ok=True)
        self._db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS setups (
                    id          TEXT PRIMARY KEY,
                    name        TEXT UNIQUE NOT NULL,
                    description TEXT,
                    definition  TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(self, name: str, definition: dict, description: str = "") -> str:
        """Insert or replace a setup. Returns the setup id."""
        setup_id = str(uuid.uuid4())
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM setups WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                setup_id = existing["id"]
                conn.execute(
                    "UPDATE setups SET description=?, definition=? WHERE id=?",
                    (description, json.dumps(definition), setup_id),
                )
            else:
                conn.execute(
                    "INSERT INTO setups (id, name, description, definition, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (setup_id, name, description, json.dumps(definition),
                     datetime.now().isoformat()),
                )
        return setup_id

    def delete(self, name_or_id: str) -> bool:
        """Delete a setup by name or id. Returns True if a row was deleted."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM setups WHERE name = ? OR id = ?",
                (name_or_id, name_or_id),
            )
            return cur.rowcount > 0

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, name_or_id: str) -> dict | None:
        """Return a setup record by name or id, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM setups WHERE name = ? OR id = ?",
                (name_or_id, name_or_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "id":          row["id"],
            "name":        row["name"],
            "description": row["description"],
            "definition":  json.loads(row["definition"]),
            "created_at":  row["created_at"],
        }

    def list(self) -> list[dict]:
        """Return all setups (without the full definition for brevity)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, created_at FROM setups ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_definition(self, name_or_id: str) -> dict | None:
        """Return just the definition dict for a setup, or None if not found."""
        record = self.get(name_or_id)
        return record["definition"] if record else None
