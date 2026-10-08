import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.rust import analyzer
from tests.golden import copy_fixture, dump_snapshot, load_snapshot, touch_indexed_files


@pytest.fixture
def without_regex_parser(monkeypatch):
    """Fail any symbol parse that doesn't go through tree-sitter."""

    def regex_parser(path, source):
        raise AssertionError(f"regex parser used for {path}")

    monkeypatch.setattr(analyzer, "parse_rust_source", regex_parser)


@pytest.mark.parametrize("name", ["rust"])
def test_tree_sitter_scan_and_refresh_match_golden_snapshots(name, tmp_path, without_regex_parser):
    project_root = copy_fixture(name, tmp_path)
    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)
    assert dump_snapshot(conn) == load_snapshot(name)

    touch_indexed_files(conn, project_root)
    refresh_index(conn, project_root, config)
    assert dump_snapshot(conn) == load_snapshot(name)
