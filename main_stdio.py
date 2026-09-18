import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from project_mcp.config import ConfigError, load_config
from project_mcp.db import get_connection
from project_mcp.indexer import get_index_status, run_scan
from project_mcp.tools.dependencies import normalize_dependency_name


def _indexed_dependencies(project_root: Path, config, ecosystem: str | None) -> list[dict]:
    if ecosystem not in (None, "python"):
        return []
    conn = get_connection(project_root)
    if get_index_status(conn)["status"] == "never_indexed":
        run_scan(conn, project_root, config)
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
