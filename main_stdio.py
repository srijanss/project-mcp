import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from project_mcp.config import ConfigError, load_config


def build_server(project_root: Path) -> MCPServer:
    load_config(project_root)
    return MCPServer("project-mcp")


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
