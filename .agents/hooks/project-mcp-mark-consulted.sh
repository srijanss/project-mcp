#!/usr/bin/env bash
# PostToolUse hook (matcher: project-mcp query tools — find_symbol,
# get_symbol_context, get_dependencies, get_dependents, get_project_overview).
# Drops a marker in this session's scratchpad_dir recording that project-mcp
# was consulted. project-mcp-reminder.sh (PreToolUse on the outside-in-tdd
# decision-point tools) requires and consumes this marker before letting a
# TDD decision point proceed, turning the old soft reminder into a hard gate.
set -euo pipefail

input="$(cat)"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -n "$scratchpad_dir" ]; then
  mkdir -p "$scratchpad_dir"
  touch "$scratchpad_dir/.project-mcp-consulted"
fi

echo '{}'
