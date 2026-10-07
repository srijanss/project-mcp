import asyncio
import json
import sys

import pytest

from project_mcp.main_stdio import build_server


@pytest.fixture
def broken_plugin_installed(tmp_path, monkeypatch):
    site = tmp_path / "site"
    dist_info = site / "broken_plugin-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: broken-plugin\nVersion: 0.1.0\n"
    )
    (dist_info / "entry_points.txt").write_text(
        "[project_mcp.plugins]\nbroken = broken_plugin:DESCRIPTOR\n"
    )
    (site / "broken_plugin.py").write_text('raise ImportError("missing toolchain")\n')
    monkeypatch.syspath_prepend(str(site))
    yield
    sys.modules.pop("broken_plugin", None)


def test_index_status_reports_active_plugins_and_failed_plugins_with_errors(
    tmp_path, broken_plugin_installed
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("def run():\n    pass\n")
    (project / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    server = build_server(project)

    result = asyncio.run(server.call_tool("get_index_status", {}))
    status = json.loads(result.content[0].text)

    assert status["plugins"] == {
        "active": ["python", "javascript", "django"],
        "failed": {"broken": "failed to load: missing toolchain"},
    }
