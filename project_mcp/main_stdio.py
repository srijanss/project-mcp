import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from project_mcp.config import ConfigError, load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, get_index_status, refresh_index
from project_mcp.tools.dependencies import normalize_dependency_name
from project_mcp.tools.project import get_project_overview
from project_mcp.tools.symbols import (
    find_symbol,
    get_dependencies,
    get_dependents,
    get_symbol_context,
)


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


def build_server(project_root: Path) -> MCPServer:
    config = load_config(project_root)
    server = MCPServer("project-mcp")

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
    def find_symbol_tool(query: str) -> list[dict]:
        """Find symbols whose name or qualified name matches the query."""
        return find_symbol(project_root, query)

    @server.tool(name="get_symbol_context")
    def get_symbol_context_tool(qualified_name: str) -> dict:
        """Return full details for one exact symbol match."""
        return get_symbol_context(project_root, qualified_name)

    @server.tool(name="get_dependencies")
    def get_dependencies_tool(qualified_name: str) -> list[dict]:
        """Return what a symbol or module imports or inherits from."""
        return get_dependencies(project_root, qualified_name)

    @server.tool(name="get_dependents")
    def get_dependents_tool(qualified_name: str) -> list[dict]:
        """Return what imports or inherits from a symbol or module."""
        return get_dependents(project_root, qualified_name)

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
