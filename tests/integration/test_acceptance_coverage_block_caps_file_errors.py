import json

from project_mcp.config import load_config
from project_mcp.coverage import coverage_block
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry


class _FailingAnalyzer:
    """Cannot analyze any file, and says so at length."""

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        raise ValueError(f"cannot parse {path}: " + "reason " * 200)

    def resolve_import(self, importer, spec):
        return []


def test_a_query_touching_many_failed_files_lists_a_bounded_sample_of_their_errors(tmp_path):
    for i in range(200):
        (tmp_path / f"f{i:03}.toy").write_text("x")
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_FailingAnalyzer",
        )
    )
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    block = coverage_block(conn, registry, set())

    entry = block["languages"]["toy"]
    assert len(json.dumps(block)) < 10_000
    assert entry["errors_total"] == 200
    assert 0 < len(entry["errors"]) < 200
    assert list(entry["errors"]) == sorted(entry["errors"])
    assert "200 files" in entry["note"]
