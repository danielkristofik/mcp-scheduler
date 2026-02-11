"""Tests for mcp_scheduler.server – async tool function tests with mocked cron."""

import json
from unittest.mock import patch, MagicMock

import pytest

from mcp_scheduler.server import (
    AddTaskInput,
    ListTasksInput,
    TaskIdInput,
    scheduler_add_task,
    scheduler_get_task,
    scheduler_list_tasks,
    scheduler_remove_task,
)


@pytest.fixture
def mock_cron():
    """Mock all cron_manager functions used by server tools."""
    with patch("mcp_scheduler.server.cron_manager") as m:
        m.install_job.return_value = "Installed: 0 7 * * *"
        m.get_next_run.return_value = "2025-01-01T07:00:00"
        m.list_jobs.return_value = []
        m.remove_job.return_value = True
        yield m


class TestAddTask:
    async def test_add_task_returns_created(self, mock_cron):
        params = AddTaskInput(
            name="Test",
            prompt="Hello",
            cron_expression="0 7 * * *",
        )
        result = json.loads(await scheduler_add_task(params))
        assert result["status"] == "created"
        assert result["task"]["name"] == "Test"
        mock_cron.install_job.assert_called_once()


class TestGetTask:
    async def test_get_existing(self, mock_cron):
        # First create
        params = AddTaskInput(name="X", prompt="Y", cron_expression="0 8 * * *")
        created = json.loads(await scheduler_add_task(params))
        task_id = created["task"]["id"]

        result = json.loads(await scheduler_get_task(TaskIdInput(task_id=task_id)))
        assert result["task"]["name"] == "X"

    async def test_get_missing(self, mock_cron):
        result = json.loads(await scheduler_get_task(TaskIdInput(task_id="nonexistent1")))
        assert "error" in result


class TestListTasks:
    async def test_list_empty(self, mock_cron):
        result = json.loads(await scheduler_list_tasks(ListTasksInput()))
        assert result["count"] == 0

    async def test_list_after_add(self, mock_cron):
        await scheduler_add_task(AddTaskInput(name="A", prompt="P", cron_expression="0 9 * * *"))
        result = json.loads(await scheduler_list_tasks(ListTasksInput()))
        assert result["count"] == 1


class TestRemoveTask:
    async def test_remove_existing(self, mock_cron):
        created = json.loads(await scheduler_add_task(
            AddTaskInput(name="R", prompt="P", cron_expression="0 10 * * *")
        ))
        task_id = created["task"]["id"]

        result = json.loads(await scheduler_remove_task(TaskIdInput(task_id=task_id)))
        assert result["status"] == "removed"

    async def test_remove_missing(self, mock_cron):
        result = json.loads(await scheduler_remove_task(TaskIdInput(task_id="nonexistent1")))
        assert "error" in result
