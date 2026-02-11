#!/usr/bin/env python3
"""
Task runner - executed by cron for each scheduled task.
1. Loads task definition from SQLite
2. Calls Claude CLI (claude -p) with the task prompt
3. Delivers the result (file, stdout, append)
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp_scheduler import task_store
from mcp_scheduler.paths import get_output_dir


def call_claude(prompt: str, model: str = "sonnet") -> dict:
    """Call Claude via the ``claude`` CLI in print mode.

    Uses ``claude -p --model <model> "prompt"`` which works with the
    user's existing Claude subscription – no API key required.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError(
            "claude CLI not found in PATH. "
            "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
        )

    cmd = [
        claude_bin,
        "-p",
        "--model", model,
        "--output-format", "json",
        prompt,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"claude CLI exited with code {result.returncode}: {stderr}")

    # --output-format json returns a JSON object with "result" key
    try:
        data = json.loads(result.stdout)
        text = data.get("result", result.stdout)
    except (json.JSONDecodeError, TypeError):
        text = result.stdout

    return {
        "text": text,
        "model": model,
    }


def deliver_file(task: dict, result: dict) -> str:
    """Save result to a file. Returns the output path."""
    config = task.get("delivery_config", {})
    fmt = config.get("format", "md")
    directory = config.get("directory", str(get_output_dir()))

    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{task['name'].replace(' ', '_').lower()}_{timestamp}.{fmt}"
    output_path = output_dir / filename

    output_path.write_text(result["text"], encoding="utf-8")
    return str(output_path)


def deliver_stdout(task: dict, result: dict) -> str:
    """Print result to stdout (useful for testing)."""
    print(result["text"])
    return "stdout"


def deliver_append(task: dict, result: dict) -> str:
    """Append result to an existing file (e.g., a running log/journal)."""
    config = task.get("delivery_config", {})
    filepath = config.get("filepath")
    if not filepath:
        raise ValueError("delivery_config.filepath required for 'append' delivery type")

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    separator = config.get("separator", f"\n\n---\n\n## {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

    with open(path, "a", encoding="utf-8") as f:
        f.write(separator)
        f.write(result["text"])

    return str(path)


# Delivery registry
DELIVERY_HANDLERS = {
    "file": deliver_file,
    "stdout": deliver_stdout,
    "append": deliver_append,
}


def run_task(task_id: str) -> None:
    """Main task execution flow."""
    # 1. Load task
    task = task_store.get_task(task_id)
    if task is None:
        print(f"ERROR: Task '{task_id}' not found", file=sys.stderr)
        sys.exit(1)

    if not task["enabled"]:
        print(f"SKIP: Task '{task_id}' is disabled", file=sys.stderr)
        return

    # 2. Log run start
    run_id = task_store.log_run_start(task_id)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Running task: {task['name']} ({task_id})")

    try:
        # 3. Call Claude via CLI
        result = call_claude(
            prompt=task["prompt"],
            model=task.get("model", "sonnet"),
        )
        print(f"  Model: {result['model']}")

        # 4. Deliver result
        delivery_type = task.get("delivery_type", "file")
        handler = DELIVERY_HANDLERS.get(delivery_type)
        if handler is None:
            raise ValueError(f"Unknown delivery type: '{delivery_type}'. Available: {list(DELIVERY_HANDLERS.keys())}")

        output_path = handler(task, result)
        print(f"  Delivered via '{delivery_type}': {output_path}")

        # 5. Log success
        task_store.log_run_finish(
            run_id,
            status="success",
            output_path=output_path,
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"  ERROR: {error_msg}", file=sys.stderr)
        task_store.log_run_finish(run_id, status="error", error=error_msg)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Claude Scheduler Task Runner")
    parser.add_argument("--task-id", required=True, help="Task ID to execute")
    parser.add_argument("--dry-run", action="store_true", help="Print task info without executing")
    args = parser.parse_args()

    if args.dry_run:
        task = task_store.get_task(args.task_id)
        if task:
            print(json.dumps(task, indent=2))
        else:
            print(f"Task not found: {args.task_id}")
        return

    run_task(args.task_id)


if __name__ == "__main__":
    main()
