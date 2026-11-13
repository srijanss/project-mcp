#!/usr/bin/env bash
# project-mcp consult gate: requires a project-mcp lookup before each gated
# TDD decision point.
#
# Usage: project-mcp-consult-gate.sh mark|check  (hook JSON on stdin)
#
#   mark   PostToolUse on the project-mcp query tools. Drops a marker in this
#          session's scratchpad_dir.
#   check  PreToolUse on the gated tools. Denies the call unless the marker
#          exists; on allow it consumes the marker, so each consult unlocks
#          exactly one gated call.
#
# There is no timestamp or TTL: a consult counts until the next gated call
# uses it up. Both modes fail open (allow, write nothing) when scratchpad_dir
# is missing from the hook input, rather than blocking the session forever.
set -euo pipefail

mode="${1:-}"
input="$(cat)"
tool="$(printf '%s' "$input" | jq -r '.tool_name // empty')"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -z "$scratchpad_dir" ]; then
  echo '{}'
  exit 0
fi

marker="$scratchpad_dir/.project-mcp-consulted"

if [ "$mode" = mark ]; then
  mkdir -p "$scratchpad_dir"
  touch "$marker"
  echo '{}'
  exit 0
fi

if [ -f "$marker" ]; then
  rm -f "$marker"
  echo '{}'
  exit 0
fi

reason="Blocked: consult project-mcp before $tool."

jq -n --arg reason "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $reason
  }
}'
