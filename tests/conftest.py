"""Shared fixtures for mcp-scheduler tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point all data to a temp directory so tests never touch real DB/cron."""
    monkeypatch.setenv("CLAUDE_SCHEDULER_DATA_DIR", str(tmp_path))

    # Reset the lazy-init flag so each test gets a fresh database
    import mcp_scheduler.task_store as ts
    ts._db_initialized = False

    yield tmp_path
