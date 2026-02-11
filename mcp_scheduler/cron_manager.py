"""
Cron manager - safe wrapper around system crontab.
Uses python-crontab to manipulate the current user's crontab.
Each managed job is tagged with a comment containing the task ID.
"""

from __future__ import annotations

import shutil
import sys
from typing import Optional

from crontab import CronTab

from mcp_scheduler.paths import get_log_dir

# Marker prefix so we only touch our own jobs
COMMENT_PREFIX = "claude-scheduler:"


def get_runner_args(task_id: str) -> list[str]:
    """Return the command list for running a task.

    Prefers the installed ``mcp-scheduler-run`` console script.
    Falls back to ``python -m mcp_scheduler.run_task``.
    """
    runner = shutil.which("mcp-scheduler-run")
    if runner:
        return [runner, "--task-id", task_id]
    return [sys.executable, "-m", "mcp_scheduler.run_task", "--task-id", task_id]


def _get_crontab() -> CronTab:
    """Get the current user's crontab."""
    return CronTab(user=True)


def _job_comment(task_id: str) -> str:
    """Generate a standardized comment for a cron job."""
    return f"{COMMENT_PREFIX}{task_id}"


def install_job(task_id: str, cron_expression: str) -> str:
    """Install a cron job for a task.

    Returns:
        String description of the installed job.
    """
    cron = _get_crontab()
    comment = _job_comment(task_id)

    # Remove existing job for this task if any
    cron.remove_all(comment=comment)

    # Build command – use absolute path so cron doesn't depend on $PATH
    args = get_runner_args(task_id)
    log_path = get_log_dir() / f"{task_id}.log"
    command = " ".join(args) + f" >> {log_path} 2>&1"

    # Create new job
    job = cron.new(command=command, comment=comment)
    job.setall(cron_expression)

    if not job.is_valid():
        raise ValueError(f"Invalid cron expression: '{cron_expression}'")

    cron.write()
    return f"Installed: {job.slices} -> {command}"


def remove_job(task_id: str) -> bool:
    """Remove a cron job for a task.

    Returns:
        True if a job was removed, False if no job found.
    """
    cron = _get_crontab()
    comment = _job_comment(task_id)
    count = cron.remove_all(comment=comment)
    cron.write()
    return count > 0


def list_jobs() -> list[dict]:
    """List all claude-scheduler managed cron jobs."""
    cron = _get_crontab()
    jobs = []
    for job in cron:
        if job.comment and job.comment.startswith(COMMENT_PREFIX):
            task_id = job.comment[len(COMMENT_PREFIX):]
            jobs.append({
                "task_id": task_id,
                "cron_expression": str(job.slices),
                "command": job.command,
                "enabled": job.is_enabled(),
                "schedule_description": job.description(use_24hour_time_format=True),
            })
    return jobs


def enable_job(task_id: str) -> bool:
    """Enable a disabled cron job."""
    cron = _get_crontab()
    comment = _job_comment(task_id)
    found = False
    for job in cron.find_comment(comment):
        job.enable()
        found = True
    if found:
        cron.write()
    return found


def disable_job(task_id: str) -> bool:
    """Disable a cron job without removing it."""
    cron = _get_crontab()
    comment = _job_comment(task_id)
    found = False
    for job in cron.find_comment(comment):
        job.enable(False)
        found = True
    if found:
        cron.write()
    return found


def get_next_run(task_id: str) -> Optional[str]:
    """Get the next scheduled run time for a task."""
    cron = _get_crontab()
    comment = _job_comment(task_id)
    for job in cron.find_comment(comment):
        schedule = job.schedule(date_from=__import__("datetime").datetime.now())
        next_run = schedule.get_next()
        return next_run.isoformat()
    return None
