from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry
from project_mcp.tools.project import get_project_overview


class _ToyAnalyzer:
    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        return FileAnalysis()

    def resolve_import(self, importer, spec):
        return []

    def list_dependencies(self, project_root):
        widgets = (project_root / "toy.deps").read_text().split()
        return [
            {"name": name, "ecosystem": "toy", "version": "1.0", "version_status": "declared"}
            for name in widgets
        ]


def _toy_registry():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_ToyAnalyzer",
            manifests=("toy.deps",),
            ecosystem="toy",
        )
    )
    return registry


def test_manifests_and_dependencies_come_from_language_plugins(tmp_path):
    (tmp_path / "main.toy").write_text("main\n")
    (tmp_path / "toy.deps").write_text("gear sprocket\n")
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n')
    registry = _toy_registry()
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert get_project_overview(tmp_path, registry=registry)["manifests"] == ["toy.deps"]
    assert conn.execute(
        "SELECT name, ecosystem, declared_version FROM dependencies ORDER BY name"
    ).fetchall() == [("gear", "toy", "1.0"), ("sprocket", "toy", "1.0")]
