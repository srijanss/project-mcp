from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry

ANALYZED = []


class _RecordingAnalyzer:
    """Indexes one module symbol per file and records each file it analyzes."""

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        ANALYZED.append(path)
        name = path.rsplit(".", 1)[0]
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


def _registry(toy_version):
    registry = PluginRegistry()
    for name, version, extension in (("toy", toy_version, ".toy"), ("other", "1.0.0", ".oth")):
        registry.register(
            PluginDescriptor(
                name=name,
                version=version,
                api_version=1,
                extensions={extension: name},
                analyzer=f"{__name__}:_RecordingAnalyzer",
            )
        )
    return registry


def _project(tmp_path):
    (tmp_path / "main.toy").write_text("main\n")
    (tmp_path / "lib.oth").write_text("lib\n")
    return get_connection(tmp_path)


def test_bumping_a_plugin_version_reindexes_only_its_files(tmp_path):
    conn = _project(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=_registry("0.1.0"))
    ANALYZED.clear()

    ensure_fresh_index(conn, tmp_path, load_config(tmp_path), registry=_registry("0.2.0"))

    assert ANALYZED == ["main.toy"]


def test_changing_a_plugins_config_reindexes_only_its_files(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "mcpctl.toml").write_text("[plugins.python]\nstrict = false\n")
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    before = dict(conn.execute("SELECT path, parser_version FROM files"))

    (tmp_path / "mcpctl.toml").write_text("[plugins.python]\nstrict = true\n")
    ensure_fresh_index(conn, tmp_path, load_config(tmp_path))
    after = dict(conn.execute("SELECT path, parser_version FROM files"))

    assert after["app.py"] != before["app.py"]
    assert after["app.py"].startswith("python@")
    assert after["lib.rs"] == before["lib.rs"]
