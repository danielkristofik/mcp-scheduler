# mcp-scheduler

An MCP server that lets Claude schedule and manage recurring tasks via system cron.

Tasks are stored in SQLite, cron handles execution timing, and a runner script calls the Claude API and delivers results.

## Installation

```bash
git clone https://github.com/youruser/mcp-scheduler.git
cd mcp-scheduler
pip install -e ".[runner,dev]"
```

`runner` pulls in the `anthropic` SDK (needed for cron-triggered task execution).
`dev` pulls in `pytest` + `pytest-asyncio`.

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "scheduler": {
      "command": "mcp-scheduler",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

### Claude Code

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "scheduler": {
      "command": "mcp-scheduler"
    }
  }
}
```

### API Key for cron

The runner needs `ANTHROPIC_API_KEY` available when cron executes. Easiest approach:

```bash
crontab -e
# Add at the top:
ANTHROPIC_API_KEY=sk-ant-...
```

## Tools

| Tool | Description |
|------|-------------|
| `scheduler_add_task` | Create a scheduled task + install cron job |
| `scheduler_list_tasks` | List all tasks with status and next run |
| `scheduler_get_task` | Get task details + recent run history |
| `scheduler_update_task` | Modify task config (prompt, schedule, etc.) |
| `scheduler_remove_task` | Delete task + remove cron job |
| `scheduler_enable_task` | Re-enable a disabled task |
| `scheduler_disable_task` | Disable task (cron job commented out) |
| `scheduler_run_now` | Execute a task immediately |
| `scheduler_list_cron` | Show raw crontab entries |
| `scheduler_task_history` | Get execution history for a task |

## Data storage

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/claude-scheduler/` |
| Linux | `$XDG_DATA_HOME/claude-scheduler/` (default `~/.local/share/`) |

Override with `CLAUDE_SCHEDULER_DATA_DIR` environment variable.

Contents:
- `tasks.db` – SQLite database
- `outputs/` – default directory for file-based delivery
- `logs/` – cron job log files

## Delivery types

| Type | Description | Config |
|------|-------------|--------|
| `file` | Save output to a file | `{format: "md"\|"txt"\|"json", directory: "/path"}` |
| `append` | Append to an existing file | `{filepath: "/path/journal.md"}` |
| `stdout` | Print to stdout (testing) | — |

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
