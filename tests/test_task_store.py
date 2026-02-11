"""Tests for mcp_scheduler.task_store – CRUD + history against real SQLite in tmp."""

from mcp_scheduler import task_store


def _make_task(**overrides):
    defaults = dict(
        name="Test Task",
        prompt="Say hello",
        cron_expression="0 7 * * *",
    )
    defaults.update(overrides)
    return task_store.create_task(**defaults)


class TestCreateAndGet:
    def test_create_returns_dict_with_id(self):
        task = _make_task()
        assert "id" in task
        assert len(task["id"]) == 12
        assert task["name"] == "Test Task"
        assert task["enabled"] is True

    def test_get_returns_same_task(self):
        task = _make_task()
        fetched = task_store.get_task(task["id"])
        assert fetched["id"] == task["id"]
        assert fetched["prompt"] == "Say hello"

    def test_get_missing_returns_none(self):
        assert task_store.get_task("nonexistent") is None


class TestList:
    def test_list_returns_all(self):
        _make_task(name="A")
        _make_task(name="B")
        tasks = task_store.list_tasks()
        assert len(tasks) == 2

    def test_list_enabled_only(self):
        t1 = _make_task(name="Enabled")
        t2 = _make_task(name="Disabled")
        task_store.update_task(t2["id"], enabled=False)
        tasks = task_store.list_tasks(enabled_only=True)
        assert len(tasks) == 1
        assert tasks[0]["name"] == "Enabled"


class TestUpdate:
    def test_update_name(self):
        task = _make_task()
        updated = task_store.update_task(task["id"], name="New Name")
        assert updated["name"] == "New Name"

    def test_update_delivery_config_dict(self):
        task = _make_task()
        updated = task_store.update_task(task["id"], delivery_config={"format": "txt"})
        assert updated["delivery_config"] == {"format": "txt"}


class TestDelete:
    def test_delete_existing(self):
        task = _make_task()
        assert task_store.delete_task(task["id"]) is True
        assert task_store.get_task(task["id"]) is None

    def test_delete_missing(self):
        assert task_store.delete_task("nonexistent") is False


class TestRunHistory:
    def test_log_and_retrieve(self):
        task = _make_task()
        run_id = task_store.log_run_start(task["id"])
        assert isinstance(run_id, int)

        task_store.log_run_finish(run_id, status="success", output_path="/tmp/out.md", tokens_used=100)

        history = task_store.get_task_history(task["id"])
        assert len(history) == 1
        assert history[0]["status"] == "success"
        assert history[0]["tokens_used"] == 100
