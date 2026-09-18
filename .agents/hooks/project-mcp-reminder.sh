#!/usr/bin/env bash
# PreToolUse hook (matcher: outside-in-tdd MCP tools that start a TDD
# decision point — init_feature, drill_down, write_test, write_test_skeleton,
# write_code, refactor_code). Enforces that a project-mcp tool (find_symbol,
# get_symbol_context, get_dependencies, get_dependents, get_project_overview)
# was called since the last such decision point, and blocks the call
# otherwise.
#
# Why this exists: a soft additionalContext reminder alone was observed to
# be followed only once per session (the first research pass), not before
# every decision point, even though the reminder fired every time. See
# project-mcp-mark-consulted.sh (PostToolUse on the project-mcp tools) for
# the other half of this — it drops the marker this script looks for.
#
# The marker lives in this session's scratchpad_dir (given in the hook
# input), so it's scoped per-session and doesn't collide across concurrent
# sessions. If scratchpad_dir isn't available for some reason, this fails
# open (allows the call) rather than permanently blocking the session.
set -euo pipefail

input="$(cat)"
tool="$(printf '%s' "$input" | jq -r '.tool_name // empty')"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -z "$scratchpad_dir" ]; then
  echo '{}'
  exit 0
fi

marker="$scratchpad_dir/.project-mcp-consulted"

if [ ! -f "$marker" ]; then
  jq -n --arg tool "$tool" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: (
        "Blocked: call a project-mcp tool (find_symbol, get_symbol_context, " +
        "get_dependencies, get_dependents, or get_project_overview) relevant " +
        "to this step, then retry " + $tool + ". This is a standing " +
        "requirement for this project — check existing project structure, " +
        "symbols, and dependencies before deciding what to test or " +
        "implement, instead of guessing or grepping from scratch."
      )
    }
  }'
else
  rm -f "$marker"
  echo '{}'
fi
