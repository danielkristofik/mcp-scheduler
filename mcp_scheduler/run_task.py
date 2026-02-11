#!/usr/bin/env python3
"""
Task runner - executed by cron for each scheduled task.
1. Loads task definition from SQLite
2. Calls Claude API with the task prompt
3. Delivers the result (file, stdout, or future: email/slack/notes)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp_scheduler import task_store
from mcp_scheduler.paths import get_output_dir


def call_claude(prompt: str, model: str = "claude-sonnet-4-20250514", max_tokens: int = 4096) -> dict:
    """Call Claude API and return the response.

    Requires ANTHROPIC_API_KEY environment variable.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run: pip install 'mcp-scheduler[runner]'", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    return {
        "text": text,
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
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
        # 3. Call Claude
        result = call_claude(
            prompt=task["prompt"],
            model=task.get("model", "claude-sonnet-4-20250514"),
            max_tokens=task.get("max_tokens", 4096),
        )
        print(f"  Tokens used: {result['total_tokens']}")

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
            tokens_used=result["total_tokens"],
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
