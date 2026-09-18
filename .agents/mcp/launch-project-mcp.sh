#!/usr/bin/env bash
# Worktree-safe launcher for the project-mcp server. Resolves PROJECT_MCP_ROOT
# from this script's own location rather than a hardcoded absolute path, so
# the same committed config works unmodified in every git worktree/checkout —
# each one has its own copy of this script at the same relative position.
#
# PROJECT_MCP_ROOT is the repository project-mcp should build/query its
# knowledge index against — i.e. the repo this script lives in, not the
# project-mcp server's own source checkout (that's wherever `project-mcp`
# itself was installed from, see .agents/mcp/README or pipx list).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export PROJECT_MCP_ROOT="$PROJECT_ROOT"

# Explicit, not just inherited: a bare `project-mcp` is resolved via PATH
# lookup, and $HOME/.local/bin (where `pipx install` puts console scripts)
# isn't guaranteed to be on whatever PATH the MCP client spawns this with.
export PATH="$PROJECT_ROOT/.venv/bin:$HOME/.local/bin:$PATH"

# Resolved via PATH (not a hardcoded ~/.local/bin path) so a worktree with
# its own .venv runs its own code; only a worktree with no .venv of its own
# falls through to the global ~/.local/bin (pipx) install.
exec project-mcp "$@"
