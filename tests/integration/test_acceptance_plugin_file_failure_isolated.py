from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry


class _FussyAnalyzer:
    """Indexes one module symbol per file, but cannot parse files saying "bad"."""

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        if "bad" in source:
            raise ValueError(f"cannot parse {path}")
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


def _registry():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_FussyAnalyzer",
        )
    )
    return registry


def _state(conn):
    return {
        "symbols": sorted(r[0] for r in conn.execute("SELECT qualified_name FROM symbols")),
        "files": dict(
            ((path, (status, error)) for path, status, error in conn.execute(
                "SELECT path, analysis_status, analysis_error FROM files ORDER BY path"
            ))
        ),
    }


def test_a_plugin_error_on_one_file_drops_only_that_files_output(tmp_path):
    (tmp_path / "good.toy").write_text("fine\n")
    (tmp_path / "broken.toy").write_text("bad\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    registry = _registry()

    run_scan(conn, tmp_path, config, registry=registry)
    after_scan = _state(conn)
    (tmp_path / "broken.toy").write_text("fixed now\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert after_scan == {
        "symbols": ["good"],
        "files": {
            "broken.toy": ("file_failed", "ValueError: cannot parse broken.toy"),
            "good.toy": ("analyzed", None),
        },
    }
    assert _state(conn) == {
        "symbols": ["broken", "good"],
        "files": {"broken.toy": ("analyzed", None), "good.toy": ("analyzed", None)},
    }
