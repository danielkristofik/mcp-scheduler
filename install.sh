#!/usr/bin/env bash
#
# mcp-scheduler install script
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/danielkristofik/mcp-scheduler/main/install.sh | bash
#   # or locally:
#   ./install.sh
#
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { printf "${BLUE}[info]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$*"; }
err()   { printf "${RED}[error]${NC} %s\n" "$*" >&2; }

# ── Config ───────────────────────────────────────────────────────────
REPO="https://github.com/danielkristofik/mcp-scheduler.git"
INSTALL_DIR="${MCP_SCHEDULER_INSTALL_DIR:-$HOME/.mcp-scheduler}"
MIN_PYTHON_MINOR=10

# ── Helpers ──────────────────────────────────────────────────────────
find_python() {
    # Try common Python 3.10+ locations
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        local bin
        bin="$(command -v "$cmd" 2>/dev/null)" || continue
        local ver
        ver="$("$bin" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)" || continue
        if [ "$ver" -ge "$MIN_PYTHON_MINOR" ]; then
            echo "$bin"
            return 0
        fi
    done
    # Homebrew fallback
    for minor in 13 12 11 10; do
        local brew_bin="/opt/homebrew/bin/python3.${minor}"
        [ -x "$brew_bin" ] && { echo "$brew_bin"; return 0; }
        brew_bin="/usr/local/bin/python3.${minor}"
        [ -x "$brew_bin" ] && { echo "$brew_bin"; return 0; }
    done
    return 1
}

# ── Pre-flight checks ───────────────────────────────────────────────
printf "\n${BOLD}mcp-scheduler installer${NC}\n"
printf "══════════════════════════\n\n"

# git
if ! command -v git &>/dev/null; then
    err "git is not installed. Please install git first."
    exit 1
fi
ok "git found"

# Python >= 3.10
PYTHON_BIN="$(find_python)" || {
    err "Python 3.10+ not found."
    if [[ "$OSTYPE" == darwin* ]]; then
        info "Install with: brew install python@3.12"
    else
        info "Install with: sudo apt install python3.12 python3.12-venv  (or equivalent)"
    fi
    exit 1
}
PYTHON_VER="$("$PYTHON_BIN" --version)"
ok "$PYTHON_VER ($PYTHON_BIN)"

# ── Clone / update ───────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning to $INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
fi
ok "Source ready"

# ── Virtual environment ──────────────────────────────────────────────
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
ok "Virtual environment at $VENV_DIR"

# ── Install package ──────────────────────────────────────────────────
info "Installing mcp-scheduler + dependencies"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>/dev/null
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR[runner]" --quiet
ok "Package installed"

# Verify console scripts
MCP_BIN="$VENV_DIR/bin/mcp-scheduler"
RUNNER_BIN="$VENV_DIR/bin/mcp-scheduler-run"
if [ ! -x "$MCP_BIN" ]; then
    err "mcp-scheduler binary not found at $MCP_BIN"
    exit 1
fi
ok "mcp-scheduler    → $MCP_BIN"
ok "mcp-scheduler-run → $RUNNER_BIN"

# ── Configure Claude Desktop ────────────────────────────────────────
configure_claude_desktop() {
    local config_dir config_file
    if [[ "$OSTYPE" == darwin* ]]; then
        config_dir="$HOME/Library/Application Support/Claude"
    else
        config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/Claude"
    fi
    config_file="$config_dir/claude_desktop_config.json"

    if [ ! -d "$config_dir" ]; then
        warn "Claude Desktop config directory not found ($config_dir), skipping."
        return
    fi

    # Build the scheduler server entry
    local server_entry
    server_entry=$(cat <<ENTRY
{
      "command": "$MCP_BIN"
    }
ENTRY
)

    if [ -f "$config_file" ]; then
        # Check if scheduler is already configured
        if "$PYTHON_BIN" -c "
import json, sys
with open('$config_file') as f:
    cfg = json.load(f)
if 'scheduler' in cfg.get('mcpServers', {}):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
            ok "Claude Desktop: scheduler already configured"
            return
        fi

        # Add scheduler to existing config
        "$PYTHON_BIN" -c "
import json
with open('$config_file') as f:
    cfg = json.load(f)
cfg.setdefault('mcpServers', {})
cfg['mcpServers']['scheduler'] = {'command': '$MCP_BIN'}
with open('$config_file', 'w') as f:
    json.dump(cfg, f, indent=2)
" && ok "Claude Desktop: scheduler added to $config_file" \
  || warn "Could not update $config_file — add scheduler manually."
    else
        # Create new config
        cat > "$config_file" <<CONF
{
  "mcpServers": {
    "scheduler": {
      "command": "$MCP_BIN"
    }
  }
}
CONF
        ok "Claude Desktop: created $config_file"
    fi
}

configure_claude_desktop

# ── Configure Claude Code ────────────────────────────────────────────
configure_claude_code() {
    local config_dir="$HOME/.claude"
    local config_file="$config_dir/mcp.json"

    mkdir -p "$config_dir"

    if [ -f "$config_file" ]; then
        if "$PYTHON_BIN" -c "
import json, sys
with open('$config_file') as f:
    cfg = json.load(f)
if 'scheduler' in cfg.get('mcpServers', {}):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
            ok "Claude Code: scheduler already configured"
            return
        fi

        "$PYTHON_BIN" -c "
import json
with open('$config_file') as f:
    cfg = json.load(f)
cfg.setdefault('mcpServers', {})
cfg['mcpServers']['scheduler'] = {'command': '$MCP_BIN'}
with open('$config_file', 'w') as f:
    json.dump(cfg, f, indent=2)
" && ok "Claude Code: scheduler added to $config_file" \
  || warn "Could not update $config_file — add scheduler manually."
    else
        cat > "$config_file" <<CONF
{
  "mcpServers": {
    "scheduler": {
      "command": "$MCP_BIN"
    }
  }
}
CONF
        ok "Claude Code: created $config_file"
    fi
}

configure_claude_code

# ── ANTHROPIC_API_KEY hint ───────────────────────────────────────────
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    printf "\n${YELLOW}${BOLD}API Key Setup${NC}\n"
    printf "The runner needs ANTHROPIC_API_KEY when cron executes tasks.\n"
    printf "Add it to your crontab:\n\n"
    printf "  ${BOLD}crontab -e${NC}\n"
    printf "  # Add at the top:\n"
    printf "  ${BOLD}ANTHROPIC_API_KEY=sk-ant-...${NC}\n\n"
else
    ok "ANTHROPIC_API_KEY is set in environment"
fi

# ── Summary ──────────────────────────────────────────────────────────
printf "\n${GREEN}${BOLD}Installation complete!${NC}\n"
printf "══════════════════════════\n"
printf "  Install dir:  ${BOLD}$INSTALL_DIR${NC}\n"
printf "  MCP server:   ${BOLD}$MCP_BIN${NC}\n"
printf "  Task runner:  ${BOLD}$RUNNER_BIN${NC}\n"

if [[ "$OSTYPE" == darwin* ]]; then
    printf "  Data dir:     ${BOLD}~/Library/Application Support/claude-scheduler/${NC}\n"
else
    printf "  Data dir:     ${BOLD}~/.local/share/claude-scheduler/${NC}\n"
fi

printf "\nRestart Claude Desktop / Claude Code to load the scheduler plugin.\n"
printf "Then try: ${BOLD}\"Schedule a daily greeting at 8 AM\"${NC}\n\n"
