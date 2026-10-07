from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.javascript.descriptor import DESCRIPTOR
from project_mcp.plugins.registry import PluginRegistry
from tests.golden import copy_fixture, dump_snapshot


def test_js_and_ts_files_are_analyzed_only_through_the_javascript_plugin(tmp_path):
    project_root = copy_fixture("react", tmp_path)
    registry = PluginRegistry()
    registry.register(replace(DESCRIPTOR, analyzer=None))
    conn = get_connection(project_root)

    run_scan(conn, project_root, load_config(project_root), registry=registry)

    assert conn.execute(
        "SELECT COUNT(*) FROM files WHERE language IN ('javascript', 'typescript')"
    ).fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0] == 0


def test_refresh_links_a_js_import_to_a_newly_added_ts_module(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.js").write_text("import { helper } from './util';\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config)

    (tmp_path / "app" / "util.ts").write_text("export function helper() {}\n")
    refresh_index(conn, tmp_path, config)

    assert {
        (str(row["source"]), str(row["target"]))
        for row in dump_snapshot(conn)["relationships"]
        if row["relationship_type"] == "imports"
    } == {(str({"file": "app/main.js"}), str({"file": "app/util.ts"}))}
