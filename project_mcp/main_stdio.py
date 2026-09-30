import functools
import inspect
import json
import os
import sys
import typing
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from project_mcp.config import ConfigError, load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, get_index_status, refresh_index
from project_mcp.tools.dependencies import normalize_dependency_name
from project_mcp.tools.architecture import get_architecture_context, get_architecture_facts
from project_mcp.tools.legacy import get_legacy_hotspots, get_legacy_signals
from project_mcp.tools.git import (
    get_change_coupling,
    get_change_history,
    get_hotspots,
)
from project_mcp.tools.project import get_project_overview
from project_mcp.tools.symbol_details import describe_symbol
from project_mcp.tools.symbols import (
    find_symbol,
    get_dependencies,
    get_dependents,
)
from project_mcp.tools.tests import get_test_summary, get_tests_for
from project_mcp.tools.context_packs import (
    get_context_for_architecture,
    get_context_for_bug,
    get_context_for_feature,
    get_context_for_refactor,
    get_context_for_symbol,
)


MAX_TOOL_OUTPUT_CHARS = 20_000
DEFAULT_FIND_SYMBOL_LIMIT = 50


def _indexed_dependencies(project_root: Path, config, ecosystem: str | None) -> list[dict]:
    if ecosystem not in (None, "python"):
        return []
    conn = get_connection(project_root)
    ensure_fresh_index(conn, project_root, config)
    project_id = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?", (str(project_root),)
    ).fetchone()[0]
    rows = conn.execute(
        """
        SELECT name, ecosystem, declared_version, resolved_version
        FROM dependencies WHERE project_id = ? AND ecosystem = 'python'
        ORDER BY name
        """,
        (project_id,),
    ).fetchall()
    return [
        {
            "name": name,
            "ecosystem": dependency_ecosystem,
            "version": resolved_version or declared_version,
            "version_status": (
                "resolved" if resolved_version else "declared" if declared_version else "unknown"
            ),
        }
        for name, dependency_ecosystem, declared_version, resolved_version in rows
    ]


def _size(value) -> int:
    return len(json.dumps(value, default=str))


def _cap_output(result):
    """Trim oversized results so clients don't overflow into a saved file."""
    if _size(result) <= MAX_TOOL_OUTPUT_CHARS:
        return result
    if isinstance(result, list):
        return _cap_list(result)
    if isinstance(result, dict):
        return _cap_dict(result)
    return result


def _cap_list(result: list) -> dict:
    low, high = 0, len(result)  # largest prefix that fits, by bisection
    while low < high:
        mid = (low + high + 1) // 2
        if _size(result[:mid]) <= MAX_TOOL_OUTPUT_CHARS:
            low = mid
        else:
            high = mid - 1
    kept = result[:low]
    return {
        "truncated": True,
        "total": len(result),
        "returned": len(kept),
        "items": kept,
    }


def _cap_dict(result: dict) -> dict:
    trimmed: dict[str, dict] = {}
    capped = {**result, "truncated": True, "truncated_fields": trimmed}
    while _size(capped) > MAX_TOOL_OUTPUT_CHARS:
        lists = [k for k, v in capped.items() if isinstance(v, list) and v]
        if not lists:
            break
        name = max(lists, key=lambda k: _size(capped[k]))
        total = trimmed.get(name, {}).get("total", len(capped[name]))
        capped[name] = capped[name][: len(capped[name]) // 2]
        trimmed[name] = {"total": total, "returned": len(capped[name])}
    return capped if trimmed else result


def _guard_tools(server: MCPServer) -> None:
    """Make every tool registered on `server` well behaved.

    Failures surface their real message (the framework hides the text of
    unexpected exceptions behind a bare "Error executing tool"; a ToolError
    keeps it), and oversized list results are trimmed and flagged.
    """
    register = server.tool

    def tool(*args, **kwargs):
        decorate = register(*args, **kwargs)

        def wrap(fn):
            @functools.wraps(fn)
            def guarded(*fn_args, **fn_kwargs):
                try:
                    return _cap_output(fn(*fn_args, **fn_kwargs))
                except ToolError:
                    raise
                except Exception as exc:
                    raise ToolError(f"{type(exc).__name__}: {exc}") from exc

            signature = inspect.signature(fn)
            if typing.get_origin(signature.return_annotation) is list:
                # A trimmed list is returned as a dict, so widen the output schema.
                guarded.__signature__ = signature.replace(
                    return_annotation=list[dict] | dict
                )
            return decorate(guarded)

        return wrap

    server.tool = tool


def build_server(project_root: Path) -> MCPServer:
    config = load_config(project_root)
    server = MCPServer("project-mcp")
    _guard_tools(server)

    @server.tool()
    def list_dependencies(ecosystem: str | None = None) -> list[dict]:
        """List Python dependencies declared by the project."""
        return _indexed_dependencies(project_root, config, ecosystem)

    @server.tool()
    def get_dependency_version(
        name: str, ecosystem: str | None = None
    ) -> dict:
        """Return a project's declared or resolved dependency version."""
        target = normalize_dependency_name(name)
        for dependency in _indexed_dependencies(project_root, config, ecosystem):
            if normalize_dependency_name(dependency["name"]) == target:
                return dependency
        return {"status": "not_found"}

    @server.tool(name="get_project_overview")
    def get_project_overview_tool() -> dict:
        """Return a summary of the project's languages, roots, and manifests."""
        return get_project_overview(project_root)

    @server.tool(name="find_symbol")
    def find_symbol_tool(
        query: str,
        limit: int = DEFAULT_FIND_SYMBOL_LIMIT,
        offset: int = 0,
        kind: str | None = None,
        include_migrations: bool = False,
    ) -> list[dict]:
        """Find symbols whose name or qualified name matches the query.

        Exact names rank first, then prefixes, then substrings. `kind` filters
        (class, function, method, field, module, ...); migrations are left out
        unless `include_migrations`. When more than `limit` symbols match, the
        result is {"truncated": true, "items": [...], "next_offset": N}: pass
        `offset=N` for the next page.
        """
        rows = find_symbol(
            project_root,
            query,
            include_migrations=include_migrations,
            kind=kind,
            limit=limit + 1,  # one extra row tells us whether another page exists
            offset=offset,
        )
        if len(rows) > limit:
            return {
                "truncated": True,
                "returned": limit,
                "next_offset": offset + limit,
                "items": rows[:limit],
            }
        return rows

    @server.tool(name="get_symbol_context")
    def get_symbol_context_tool(qualified_name: str) -> dict:
        """Return one symbol's location, source, direct callers/callees and tests.

        `source` is cut at 80 lines (see `source_truncated`); tests fall back
        to the enclosing module's, marked `scope: "module"`.
        """
        return describe_symbol(project_root, qualified_name)

    @server.tool(name="get_dependencies")
    def get_dependencies_tool(qualified_name: str) -> list[dict]:
        """Return what a symbol or module imports or inherits from."""
        return get_dependencies(project_root, qualified_name)

    @server.tool(name="get_dependents")
    def get_dependents_tool(qualified_name: str) -> list[dict]:
        """Return what imports or inherits from a symbol or module."""
        return get_dependents(project_root, qualified_name)

    @server.tool(name="get_tests_for")
    def get_tests_for_tool(qualified_name: str) -> list[dict]:
        """Return tests associated with a source module or symbol, with confidence and evidence."""
        return get_tests_for(project_root, qualified_name)

    @server.tool(name="get_test_summary")
    def get_test_summary_tool() -> dict:
        """Return project-wide test counts and test-relationship confidence breakdown."""
        return get_test_summary(project_root)

    @server.tool(name="get_index_status")
    def get_index_status_tool() -> dict:
        """Return whether the local index is fresh, stale, or never indexed."""
        conn = get_connection(project_root)
        return get_index_status(conn, project_root, config)

    @server.tool(name="refresh_index")
    def refresh_index_tool() -> dict:
        """Force an incremental re-index of changed/new/deleted files."""
        conn = get_connection(project_root)
        refresh_index(conn, project_root, config)
        return get_index_status(conn, project_root, config)

    @server.tool(name="get_change_history")
    def get_change_history_tool(path: str) -> dict:
        """Return a file's git change count and last-changed date."""
        return get_change_history(project_root, path)

    @server.tool(name="get_hotspots")
    def get_hotspots_tool() -> list[dict]:
        """Return high-churn files (git hotspots)."""
        return get_hotspots(project_root)

    @server.tool(name="get_change_coupling")
    def get_change_coupling_tool(path: str) -> list[dict]:
        """Return files historically changed together with a target file."""
        return get_change_coupling(project_root, path)

    @server.tool(name="get_architecture_facts")
    def get_architecture_facts_tool() -> list[dict]:
        """Return all indexed explicit architecture facts."""
        return get_architecture_facts(project_root)

    @server.tool(name="get_architecture_context")
    def get_architecture_context_tool(area: str | None = None) -> dict:
        """Return explicit architecture facts, optionally filtered to an area."""
        return get_architecture_context(project_root, area)

    @server.tool(name="get_legacy_hotspots")
    def get_legacy_hotspots_tool(limit: int = 20) -> list[dict]:
        """Return targets ranked by number of evidence-backed legacy signals."""
        return get_legacy_hotspots(project_root, limit)

    @server.tool(name="get_legacy_signals")
    def get_legacy_signals_tool(target: str) -> list[dict]:
        """Return evidence-backed legacy signals for a single target."""
        return get_legacy_signals(project_root, target)

    @server.tool(name="get_context_for_symbol")
    def get_context_for_symbol_tool(qualified_name: str) -> dict:
        """Return a compact context pack for a specific symbol."""
        return get_context_for_symbol(project_root, qualified_name)

    @server.tool(name="get_context_for_feature")
    def get_context_for_feature_tool(query: str) -> dict:
        """Return a compact context pack for a feature query."""
        return get_context_for_feature(project_root, query)

    @server.tool(name="get_context_for_bug")
    def get_context_for_bug_tool(query: str) -> dict:
        """Return a compact context pack for a bug investigation query."""
        return get_context_for_bug(project_root, query)

    @server.tool(name="get_context_for_refactor")
    def get_context_for_refactor_tool(target: str) -> dict:
        """Return a compact context pack for a refactor target."""
        return get_context_for_refactor(project_root, target)

    @server.tool(name="get_context_for_architecture")
    def get_context_for_architecture_tool(area: str) -> dict:
        """Return a compact context pack for an architecture area."""
        return get_context_for_architecture(project_root, area)

    return server


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        project_root = Path(argv[0])
    elif "PROJECT_MCP_ROOT" in os.environ:
        project_root = Path(os.environ["PROJECT_MCP_ROOT"])
    else:
        project_root = Path.cwd()

    try:
        server = build_server(project_root)
    except ConfigError as exc:
        print(f"project-mcp: startup error: {exc}", file=sys.stderr)
        return 1

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
