import sys
import textwrap

import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

TOY_PLUGIN = textwrap.dedent(
    '''
    from project_mcp.plugins.analysis import FileAnalysis
    from project_mcp.plugins.descriptor import PluginDescriptor


    class ToyAnalyzer:
        def is_test_file(self, path):
            return False

        def analyze(self, path, source):
            name = path.removesuffix(".toy")
            return FileAnalysis(
                symbols=[
                    {
                        "name": name,
                        "qualified_name": name,
                        "kind": "module",
                        "start_line": 1,
                        "end_line": 1,
                        "visibility": "public",
                    }
                ]
            )

        def resolve_import(self, importer, spec):
            return []


    DESCRIPTOR = PluginDescriptor(
        name="toy",
        version="0.1.0",
        api_version=1,
        extensions={".toy": "toy"},
        analyzer="toy_plugin:ToyAnalyzer",
    )
    '''
)


@pytest.fixture
def toy_plugin_installed(tmp_path, monkeypatch):
    site = tmp_path / "site"
    dist_info = site / "toy_plugin-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: toy-plugin\nVersion: 0.1.0\n")
    (dist_info / "entry_points.txt").write_text(
        "[project_mcp.plugins]\ntoy = toy_plugin:DESCRIPTOR\n"
    )
    (site / "toy_plugin.py").write_text(TOY_PLUGIN)
    monkeypatch.syspath_prepend(str(site))
    yield
    sys.modules.pop("toy_plugin", None)


def test_an_installed_entry_point_plugin_analyzes_its_language(tmp_path, toy_plugin_installed):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.toy").write_text("main\n")
    conn = get_connection(project)

    run_scan(conn, project, load_config(project))

    assert conn.execute(
        "SELECT f.language, s.qualified_name FROM symbols s JOIN files f ON f.id = s.file_id"
        " WHERE f.path = 'main.toy'"
    ).fetchall() == [("toy", "main")]
