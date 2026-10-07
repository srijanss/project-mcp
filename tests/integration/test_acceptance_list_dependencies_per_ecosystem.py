import asyncio
import json

from project_mcp.main_stdio import build_server


def _call(server, tool, arguments):
    result = asyncio.run(server.call_tool(tool, arguments))
    if result.structured_content is not None:
        return result.structured_content["result"]
    return json.loads(result.content[0].text)


def _names(result):
    return sorted((d["name"], d["ecosystem"]) for d in result["items"])


def test_list_dependencies_covers_every_ecosystem(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n')
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.2.0"}}\n')
    server = build_server(tmp_path)

    assert _names(_call(server, "list_dependencies", {})) == [
        ("react", "npm"),
        ("requests", "python"),
        ("serde", "rust"),
    ]
    assert _names(_call(server, "list_dependencies", {"ecosystem": "rust"})) == [
        ("serde", "rust")
    ]
    react = _call(server, "get_dependency_version", {"name": "react"})
    react.pop("coverage")
    assert react == {
        "name": "react",
        "ecosystem": "npm",
        "version": "^18.2.0",
        "version_status": "declared",
    }
