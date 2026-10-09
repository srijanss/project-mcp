import json

from project_mcp.config import load_config
from project_mcp.coverage import coverage_block
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry


class _FailingAnalyzer:
    """Cannot analyze any file, and says so in non-ASCII text that JSON escapes."""

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        raise ValueError("é" * 400)

    def resolve_import(self, importer, spec):
        return []


def test_long_paths_and_escaped_messages_do_not_grow_the_coverage_block_past_its_budget(tmp_path):
    deep = tmp_path.joinpath(*("d" * 200 for _ in range(4)))
    deep.mkdir(parents=True)
    for i in range(20):
        (deep / f"f{i:02}.toy").write_text("x")
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
    assert len(json.dumps(block)) < 7_000
    assert entry["errors_total"] == 20
    assert 0 < len(entry["errors"]) < 20
