from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from tests.golden import copy_fixture, dump_snapshot, golden_config, load_snapshot

REACT_RELATIONSHIPS = {"renders", "routes_to"}


def _schema(conn):
    return sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())


def _scan(tmp_path, name, config_for):
    project_root = copy_fixture("react", tmp_path / name)
    conn = get_connection(project_root)
    run_scan(conn, project_root, config_for(project_root))
    return conn


def test_with_react_disabled_the_fixture_scan_is_the_generic_javascript_model(tmp_path):
    conn = _scan(tmp_path, "off", golden_config)

    snapshot = dump_snapshot(conn)

    assert snapshot == load_snapshot("react")
    assert all(
        not {"framework_kind", "routes", "partial"} & set(symbol["metadata"] or {})
        for symbol in snapshot["symbols"]
    )
    assert not any(r["relationship_type"] in REACT_RELATIONSHIPS for r in snapshot["relationships"])


def test_enabling_react_only_adds_metadata_and_relationships_to_the_generic_model(tmp_path):
    off = dump_snapshot(_scan(tmp_path, "off", golden_config))
    on_conn = _scan(tmp_path, "on", load_config)
    on = dump_snapshot(on_conn)

    assert on["files"] == off["files"]
    assert [
        {k: v for k, v in symbol.items() if k != "metadata"} for symbol in on["symbols"]
    ] == [{k: v for k, v in symbol.items() if k != "metadata"} for symbol in off["symbols"]]
    assert any(
        (symbol["metadata"] or {}).get("framework_kind", "").startswith("react_")
        for symbol in on["symbols"]
    )
    assert [r for r in on["relationships"] if r["relationship_type"] not in REACT_RELATIONSHIPS] == (
        off["relationships"]
    )


def test_react_enrichment_changes_no_core_schema(tmp_path):
    off = _schema(_scan(tmp_path, "off", golden_config))
    on = _schema(_scan(tmp_path, "on", load_config))

    assert on == off
