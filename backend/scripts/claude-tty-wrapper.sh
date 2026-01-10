#!/bin/bash
# Wrapper script to run Claude CLI with fake TTY
# Fixes: https://github.com/anthropics/claude-code/issues/9026
# Usage: claude-tty-wrapper.sh [claude args...]

CLAUDE_CLI="${CLAUDE_CLI_PATH:-/home/kasadis/.local/bin/claude}"

# Use script to fake a TTY for the Claude CLI
# -q: quiet mode (no start/end messages)
# /dev/null: discard the typescript file
exec script -q /dev/null -c "$CLAUDE_CLI $*"
