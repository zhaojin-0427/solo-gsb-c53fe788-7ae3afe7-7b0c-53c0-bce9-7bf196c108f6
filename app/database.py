"""SQLite persistence for projects and authorizations."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_DIR = os.environ.get("APP_DB_DIR", "data")
DB_PATH = os.path.join(DB_DIR, "app.db")


def get_db() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            timeline TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS authorizations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_start INTEGER NOT NULL,
            source_end INTEGER NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL,
            region TEXT NOT NULL,
            channel TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


# ---------- projects ----------

def create_project(name: str, timeline: dict) -> dict:
    pid = new_id()
    created = _now()
    conn = get_db()
    conn.execute(
        "INSERT INTO projects (id, name, timeline, created_at) VALUES (?, ?, ?, ?)",
        (pid, name, json.dumps(timeline, ensure_ascii=False), created),
    )
    conn.commit()
    conn.close()
    return {"id": pid, "name": name, "created_at": created}


def list_projects() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, timeline, created_at FROM projects ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        tl = json.loads(r["timeline"])
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "created_at": r["created_at"],
                "total_frames": tl.get("total_frames"),
                "clip_count": len(tl.get("clips", [])),
            }
        )
    return out


def get_project(pid: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "timeline": json.loads(row["timeline"]),
        "created_at": row["created_at"],
    }


def delete_project(pid: str) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


# ---------- authorizations ----------

def create_authorization(project_id: str, auth: dict) -> dict:
    aid = new_id()
    conn = get_db()
    conn.execute(
        """INSERT INTO authorizations
           (id, project_id, source_start, source_end, valid_from, valid_to, region, channel)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            aid,
            project_id,
            auth["source_start"],
            auth["source_end"],
            auth["valid_from"],
            auth["valid_to"],
            auth["region"],
            auth["channel"],
        ),
    )
    conn.commit()
    conn.close()
    return {"id": aid, **auth}


def list_authorizations(project_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM authorizations WHERE project_id = ? ORDER BY source_start",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_authorization(aid: str, auth: dict) -> bool:
    conn = get_db()
    cur = conn.execute(
        """UPDATE authorizations SET
               source_start = ?, source_end = ?, valid_from = ?, valid_to = ?,
               region = ?, channel = ?
           WHERE id = ?""",
        (
            auth["source_start"],
            auth["source_end"],
            auth["valid_from"],
            auth["valid_to"],
            auth["region"],
            auth["channel"],
            aid,
        ),
    )
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


def delete_authorization(aid: str) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM authorizations WHERE id = ?", (aid,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0
