"""
SQLite-based task store for scheduled Claude tasks.
Stores task definitions (prompt, schedule, delivery config) independently of crontab.
"""

from __future__ import annotations

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from mcp_scheduler.paths import get_db_path

_db_initialized = False


def _get_conn() -> sqlite3.Connection:
    global _db_initialized
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _db_initialized:
        _init_db(conn)
        _db_initialized = True
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            cron_expression TEXT NOT NULL,
            delivery_type TEXT NOT NULL DEFAULT 'file',
            delivery_config TEXT NOT NULL DEFAULT '{}',
            model TEXT NOT NULL DEFAULT 'sonnet',
            max_tokens INTEGER NOT NULL DEFAULT 4096,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            output_path TEXT,
            error TEXT,
            tokens_used INTEGER,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
    """)
    conn.commit()


def create_task(
    name: str,
    prompt: str,
    cron_expression: str,
    delivery_type: str = "file",
    delivery_config: Optional[dict] = None,
    model: str = "sonnet",
    max_tokens: int = 4096,
) -> dict:
    """Create a new task definition. Returns the task dict."""
    task_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO tasks (id, name, prompt, cron_expression, delivery_type, delivery_config, model, max_tokens, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            name,
            prompt,
            cron_expression,
            delivery_type,
            json.dumps(delivery_config or {}),
            model,
            max_tokens,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return get_task(task_id)


def get_task(task_id: str) -> Optional[dict]:
    """Get a single task by ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_dict(row)


def list_tasks(enabled_only: bool = False) -> list[dict]:
    """List all tasks, optionally filtering to enabled only."""
    conn = _get_conn()
    if enabled_only:
        rows = conn.execute("SELECT * FROM tasks WHERE enabled = 1 ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def update_task(task_id: str, **kwargs) -> Optional[dict]:
    """Update task fields. Allowed: name, prompt, cron_expression, delivery_type, delivery_config, model, max_tokens, enabled."""
    allowed = {"name", "prompt", "cron_expression", "delivery_type", "delivery_config", "model", "max_tokens", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_task(task_id)

    if "delivery_config" in updates and isinstance(updates["delivery_config"], dict):
        updates["delivery_config"] = json.dumps(updates["delivery_config"])

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]

    conn = _get_conn()
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return get_task(task_id)


def delete_task(task_id: str) -> bool:
    """Delete a task and its run history."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def log_run_start(task_id: str) -> int:
    """Log the start of a task run. Returns the run ID."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO task_runs (task_id, started_at, status) VALUES (?, ?, 'running')",
        (task_id, now),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def log_run_finish(run_id: int, status: str, output_path: str = None, error: str = None, tokens_used: int = None) -> None:
    """Log the completion of a task run."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE task_runs SET finished_at = ?, status = ?, output_path = ?, error = ?, tokens_used = ? WHERE id = ?",
        (now, status, output_path, error, tokens_used, run_id),
    )
    conn.commit()
    conn.close()


def get_task_history(task_id: str, limit: int = 20) -> list[dict]:
    """Get run history for a task."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
        (task_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "delivery_config" in d:
        try:
            d["delivery_config"] = json.loads(d["delivery_config"])
        except (json.JSONDecodeError, TypeError):
            pass
    d["enabled"] = bool(d.get("enabled", 0))
    return d
