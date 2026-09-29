"""SQLite 持久化：工程、时间线、授权与最近一次核验结果。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    timeline TEXT,
    fps INTEGER NOT NULL DEFAULT 25,
    last_verify TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authorizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    material_id TEXT NOT NULL,
    src_lo INTEGER NOT NULL,
    src_hi INTEGER NOT NULL,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    region TEXT NOT NULL,
    channel TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_project ON authorizations(project_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def row_to_project(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "fps": row["fps"],
        "timeline": json.loads(row["timeline"]) if row["timeline"] else None,
        "last_verify": json.loads(row["last_verify"]) if row["last_verify"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_project(conn: sqlite3.Connection, name: str) -> dict:
    cur = conn.execute(
        "INSERT INTO projects (name, created_at, updated_at) VALUES (?, ?, ?)",
        (name, _now(), _now()),
    )
    return get_project(conn, cur.lastrowid)


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    return [row_to_project(r) for r in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row_to_project(row) if row else None


def save_timeline(conn: sqlite3.Connection, project_id: int, timeline: dict) -> dict:
    conn.execute(
        "UPDATE projects SET timeline = ?, fps = ?, last_verify = NULL, "
        "updated_at = ? WHERE id = ?",
        (json.dumps(timeline, ensure_ascii=False),
         timeline.get("fps", 25), _now(), project_id),
    )
    return get_project(conn, project_id)


def save_last_verify(conn: sqlite3.Connection, project_id: int, result: dict) -> None:
    conn.execute(
        "UPDATE projects SET last_verify = ?, updated_at = ? WHERE id = ?",
        (json.dumps(result, ensure_ascii=False), _now(), project_id),
    )


def rename_project(conn: sqlite3.Connection, project_id: int, name: str) -> None:
    conn.execute(
        "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
        (name, _now(), project_id),
    )


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def row_to_auth(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "material_id": row["material_id"],
        "src_lo": row["src_lo"],
        "src_hi": row["src_hi"],
        "date_from": row["date_from"],
        "date_to": row["date_to"],
        "region": row["region"],
        "channel": row["channel"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def list_authorizations(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM authorizations WHERE project_id = ? "
        "ORDER BY material_id, src_lo, id",
        (project_id,),
    ).fetchall()
    return [row_to_auth(r) for r in rows]


def add_authorization(conn: sqlite3.Connection, project_id: int, a: dict) -> dict:
    cur = conn.execute(
        "INSERT INTO authorizations (project_id, material_id, src_lo, src_hi, "
        "date_from, date_to, region, channel, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, a["material_id"], a["src_lo"], a["src_hi"],
         a["date_from"], a["date_to"], a["region"], a["channel"],
         a.get("note", ""), _now()),
    )
    row = conn.execute("SELECT * FROM authorizations WHERE id = ?",
                       (cur.lastrowid,)).fetchone()
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (_now(), project_id))
    return row_to_auth(row)


def delete_authorization(conn: sqlite3.Connection, project_id: int, auth_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM authorizations WHERE id = ? AND project_id = ?",
        (auth_id, project_id),
    )
    if cur.rowcount:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?",
                     (_now(), project_id))
    return cur.rowcount > 0
