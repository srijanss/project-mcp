#!/usr/bin/env bash
# PostToolUse hook (matcher: project-mcp query tools — find_symbol,
# get_symbol_context, get_dependencies, get_dependents, get_project_overview).
# Drops a marker in this session's scratchpad_dir recording that project-mcp
# was consulted, stamped with the current epoch time. project-mcp-reminder.sh
# (PreToolUse on the outside-in-tdd decision-point tools) requires a marker
# no older than its TTL and consumes it before letting a TDD decision point
# proceed, turning the old soft reminder into a hard, freshness-checked gate.
#
# The timestamp is written as file content (epoch seconds) rather than relied
# on via mtime, since stat's mtime flag differs between BSD/macOS and GNU —
# reading file content is portable across both.
set -euo pipefail

input="$(cat)"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -n "$scratchpad_dir" ]; then
  mkdir -p "$scratchpad_dir"
  date +%s > "$scratchpad_dir/.project-mcp-consulted"
fi

echo '{}'
