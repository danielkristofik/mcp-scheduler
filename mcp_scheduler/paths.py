"""Centralised path helpers for data directory, database, outputs, and logs."""

import os
import sys
from pathlib import Path


def get_data_dir() -> Path:
    """Return the data directory for claude-scheduler.

    Priority:
      1. CLAUDE_SCHEDULER_DATA_DIR env var (used by tests)
      2. macOS: ~/Library/Application Support/claude-scheduler/
      3. Linux/other: $XDG_DATA_HOME/claude-scheduler/ (default ~/.local/share/)
    """
    env = os.environ.get("CLAUDE_SCHEDULER_DATA_DIR")
    if env:
        p = Path(env)
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "claude-scheduler"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        p = Path(xdg) / "claude-scheduler"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path() -> Path:
    """Return the path to the SQLite database."""
    return get_data_dir() / "tasks.db"


def get_output_dir() -> Path:
    """Return the default output directory for file-based delivery."""
    d = get_data_dir() / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_log_dir() -> Path:
    """Return the log directory for cron job output."""
    d = get_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
