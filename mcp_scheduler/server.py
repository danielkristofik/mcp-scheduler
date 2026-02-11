"""
Claude Scheduler MCP Server
============================

A thin MCP wrapper over system cron that lets Claude schedule and manage
recurring tasks. Tasks are stored in SQLite, cron handles execution timing,
and a runner script calls Claude API + delivers results.

Tools:
  - scheduler_add_task:     Create a scheduled task + install cron job
  - scheduler_list_tasks:   List all managed tasks with their schedules
  - scheduler_get_task:     Get task details + run history
  - scheduler_update_task:  Modify a task (prompt, schedule, delivery, etc.)
  - scheduler_remove_task:  Delete task + remove cron job
  - scheduler_enable_task:  Enable a disabled task
  - scheduler_disable_task: Disable a task (keeps cron job but commented out)
  - scheduler_run_now:      Immediately execute a task (for testing)
  - scheduler_list_cron:    Show raw crontab entries managed by scheduler
  - scheduler_task_history: Get execution history for a task
"""

import json
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

from mcp_scheduler import task_store, cron_manager

mcp = FastMCP("scheduler_mcp")


# ─── Pydantic Input Models ──────────────────────────────────────────


class AddTaskInput(BaseModel):
    """Input for creating a new scheduled task."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        ...,
        description="Human-readable task name (e.g., 'Daily Market Briefing')",
        min_length=1,
        max_length=200,
    )
    prompt: str = Field(
        ...,
        description="The prompt to send to Claude when this task runs. Be specific and detailed.",
        min_length=1,
    )
    cron_expression: str = Field(
        ...,
        description=(
            "Standard cron expression with 5 fields: minute hour day_of_month month day_of_week. "
            "Examples: '0 7 * * *' (daily 7AM), '0 7 * * 1-5' (weekdays 7AM), "
            "'*/30 * * * *' (every 30 min), '0 9 1 * *' (1st of month 9AM)"
        ),
    )
    delivery_type: str = Field(
        default="file",
        description="How to deliver results: 'file' (save to disk), 'stdout' (print), 'append' (append to existing file)",
    )
    delivery_config: Optional[dict] = Field(
        default=None,
        description=(
            "Delivery-specific config. For 'file': {format: 'md'|'txt'|'json', directory: '/path'}. "
            "For 'append': {filepath: '/path/to/file.md', separator: '---'}."
        ),
    )
    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use (e.g., 'claude-sonnet-4-20250514', 'claude-haiku-4-5-20251001')",
    )
    max_tokens: int = Field(
        default=4096,
        description="Maximum tokens for Claude's response",
        ge=100,
        le=64000,
    )


class TaskIdInput(BaseModel):
    """Input requiring just a task ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., description="Task ID (12-character hex string)", min_length=1, max_length=20)


class UpdateTaskInput(BaseModel):
    """Input for updating an existing task."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., description="Task ID to update", min_length=1, max_length=20)
    name: Optional[str] = Field(default=None, description="New task name")
    prompt: Optional[str] = Field(default=None, description="New prompt")
    cron_expression: Optional[str] = Field(default=None, description="New cron expression")
    delivery_type: Optional[str] = Field(default=None, description="New delivery type")
    delivery_config: Optional[dict] = Field(default=None, description="New delivery config")
    model: Optional[str] = Field(default=None, description="New model")
    max_tokens: Optional[int] = Field(default=None, description="New max tokens", ge=100, le=64000)


class TaskHistoryInput(BaseModel):
    """Input for retrieving task run history."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., description="Task ID", min_length=1, max_length=20)
    limit: int = Field(default=10, description="Number of recent runs to return", ge=1, le=100)


class ListTasksInput(BaseModel):
    """Input for listing tasks."""
    model_config = ConfigDict(extra="forbid")

    enabled_only: bool = Field(default=False, description="Only show enabled tasks")


# ─── Tools ───────────────────────────────────────────────────────────


@mcp.tool(
    name="scheduler_add_task",
    annotations={
        "title": "Schedule a New Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def scheduler_add_task(params: AddTaskInput) -> str:
    """Create a new scheduled task with a cron job.

    This creates a task definition in the local database and installs
    a matching cron job. When the cron triggers, it runs the task prompt
    through Claude API and delivers the result.

    Args:
        params (AddTaskInput): Task definition including name, prompt,
            cron_expression, delivery settings, and model config.

    Returns:
        str: JSON with created task details and cron job info.
    """
    try:
        # Create task in store
        task = task_store.create_task(
            name=params.name,
            prompt=params.prompt,
            cron_expression=params.cron_expression,
            delivery_type=params.delivery_type,
            delivery_config=params.delivery_config,
            model=params.model,
            max_tokens=params.max_tokens,
        )

        # Install cron job
        cron_info = cron_manager.install_job(task["id"], params.cron_expression)
        next_run = cron_manager.get_next_run(task["id"])

        return json.dumps(
            {
                "status": "created",
                "task": task,
                "cron": cron_info,
                "next_run": next_run,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


@mcp.tool(
    name="scheduler_list_tasks",
    annotations={
        "title": "List All Scheduled Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_list_tasks(params: ListTasksInput) -> str:
    """List all scheduled tasks with their current status and next run time.

    Args:
        params (ListTasksInput): Optional filter for enabled_only.

    Returns:
        str: JSON array of tasks with schedule info.
    """
    tasks = task_store.list_tasks(enabled_only=params.enabled_only)
    cron_jobs = {j["task_id"]: j for j in cron_manager.list_jobs()}

    enriched = []
    for task in tasks:
        cj = cron_jobs.get(task["id"])
        task["cron_installed"] = cj is not None
        task["next_run"] = cron_manager.get_next_run(task["id"])
        if cj:
            task["cron_enabled"] = cj["enabled"]
            task["schedule_description"] = cj.get("schedule_description", "")
        enriched.append(task)

    return json.dumps({"count": len(enriched), "tasks": enriched}, indent=2)


@mcp.tool(
    name="scheduler_get_task",
    annotations={
        "title": "Get Task Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_get_task(params: TaskIdInput) -> str:
    """Get detailed information about a specific task including recent run history.

    Args:
        params (TaskIdInput): The task ID to look up.

    Returns:
        str: JSON with task details, cron status, and last 5 runs.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    task["next_run"] = cron_manager.get_next_run(params.task_id)
    history = task_store.get_task_history(params.task_id, limit=5)

    return json.dumps({"task": task, "recent_runs": history}, indent=2)


@mcp.tool(
    name="scheduler_update_task",
    annotations={
        "title": "Update a Scheduled Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def scheduler_update_task(params: UpdateTaskInput) -> str:
    """Update an existing task's configuration. If cron_expression changes, the cron job is reinstalled.

    Args:
        params (UpdateTaskInput): Task ID and fields to update.

    Returns:
        str: JSON with updated task details.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    updates = params.model_dump(exclude_none=True, exclude={"task_id"})
    if not updates:
        return json.dumps({"status": "no_changes", "task": task})

    updated = task_store.update_task(params.task_id, **updates)

    # Reinstall cron if expression changed
    if "cron_expression" in updates:
        cron_manager.install_job(params.task_id, updates["cron_expression"])

    updated["next_run"] = cron_manager.get_next_run(params.task_id)
    return json.dumps({"status": "updated", "task": updated}, indent=2)


@mcp.tool(
    name="scheduler_remove_task",
    annotations={
        "title": "Remove a Scheduled Task",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_remove_task(params: TaskIdInput) -> str:
    """Permanently delete a task and its cron job. Run history is also deleted.

    Args:
        params (TaskIdInput): The task ID to remove.

    Returns:
        str: JSON confirmation of deletion.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    cron_removed = cron_manager.remove_job(params.task_id)
    db_removed = task_store.delete_task(params.task_id)

    return json.dumps({
        "status": "removed",
        "task_name": task["name"],
        "cron_removed": cron_removed,
        "db_removed": db_removed,
    })


@mcp.tool(
    name="scheduler_enable_task",
    annotations={
        "title": "Enable a Disabled Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_enable_task(params: TaskIdInput) -> str:
    """Enable a previously disabled task. Re-enables both the DB flag and cron job.

    Args:
        params (TaskIdInput): The task ID to enable.

    Returns:
        str: JSON with updated status.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    task_store.update_task(params.task_id, enabled=True)
    cron_manager.enable_job(params.task_id)
    next_run = cron_manager.get_next_run(params.task_id)

    return json.dumps({"status": "enabled", "task_name": task["name"], "next_run": next_run})


@mcp.tool(
    name="scheduler_disable_task",
    annotations={
        "title": "Disable a Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_disable_task(params: TaskIdInput) -> str:
    """Disable a task without deleting it. The cron job is commented out.

    Args:
        params (TaskIdInput): The task ID to disable.

    Returns:
        str: JSON confirmation.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    task_store.update_task(params.task_id, enabled=False)
    cron_manager.disable_job(params.task_id)

    return json.dumps({"status": "disabled", "task_name": task["name"]})


@mcp.tool(
    name="scheduler_run_now",
    annotations={
        "title": "Run Task Immediately",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def scheduler_run_now(params: TaskIdInput) -> str:
    """Execute a task immediately (outside of its normal schedule). Useful for testing.

    This spawns the runner script as a subprocess so it doesn't block the MCP server.
    Check task history for the result.

    Args:
        params (TaskIdInput): The task ID to run.

    Returns:
        str: JSON with execution status.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    runner_args = cron_manager.get_runner_args(params.task_id)

    try:
        result = subprocess.run(
            runner_args,
            capture_output=True,
            text=True,
            timeout=120,
        )

        return json.dumps({
            "status": "completed" if result.returncode == 0 else "failed",
            "task_name": task["name"],
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "timeout", "task_name": task["name"], "error": "Task exceeded 120s timeout"})
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"})


@mcp.tool(
    name="scheduler_list_cron",
    annotations={
        "title": "List Raw Cron Jobs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_list_cron(params: ListTasksInput) -> str:
    """Show all cron jobs managed by the scheduler (raw crontab view).

    Args:
        params (ListTasksInput): Unused, kept for consistency.

    Returns:
        str: JSON array of cron job entries.
    """
    jobs = cron_manager.list_jobs()
    return json.dumps({"count": len(jobs), "jobs": jobs}, indent=2)


@mcp.tool(
    name="scheduler_task_history",
    annotations={
        "title": "Task Execution History",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scheduler_task_history(params: TaskHistoryInput) -> str:
    """Get the execution history for a task, including timestamps, status, and token usage.

    Args:
        params (TaskHistoryInput): Task ID and optional limit.

    Returns:
        str: JSON array of run records.
    """
    task = task_store.get_task(params.task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {params.task_id}"})

    history = task_store.get_task_history(params.task_id, limit=params.limit)
    return json.dumps({
        "task_name": task["name"],
        "count": len(history),
        "runs": history,
    }, indent=2)


# ─── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
