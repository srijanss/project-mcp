#!/usr/bin/env bash
# PostToolUse hook (matcher: project-mcp query tools — find_symbol,
# get_symbol_context, get_dependencies, get_dependents, get_project_overview).
# Drops .project-mcp-session-consulted in this session's scratchpad_dir: a
# plain existence flag, never deleted once written. project-mcp-session-gate.sh
# (PreToolUse on Bash/Read) checks only for its presence, so once project-mcp
# has been consulted ONCE this session, cold code exploration is unblocked
# for the rest of the session.
#
# The consumable per-decision marker (.project-mcp-consulted) is written only
# by project-mcp-consult-gate.sh mark. Matching hooks run in parallel, so a
# second writer could recreate it after a gated call consumed it.
set -euo pipefail

input="$(cat)"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -n "$scratchpad_dir" ]; then
  mkdir -p "$scratchpad_dir"
  touch "$scratchpad_dir/.project-mcp-session-consulted"
fi

echo '{}'
