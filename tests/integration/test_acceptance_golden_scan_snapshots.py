import pytest

from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from tests.golden import (
    FIXTURES,
    copy_fixture,
    dump_snapshot,
    golden_config,
    load_snapshot,
    touch_indexed_files,
)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_scan_output_matches_golden_snapshot(name, tmp_path):
    project_root = copy_fixture(name, tmp_path)
    conn = get_connection(project_root)

    run_scan(conn, project_root, golden_config(project_root))

    assert dump_snapshot(conn) == load_snapshot(name)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_refresh_output_matches_golden_snapshot(name, tmp_path):
    project_root = copy_fixture(name, tmp_path)
    conn = get_connection(project_root)
    config = golden_config(project_root)
    run_scan(conn, project_root, config)
    touch_indexed_files(conn, project_root)

    refresh_index(conn, project_root, config)

    assert dump_snapshot(conn) == load_snapshot(name)
