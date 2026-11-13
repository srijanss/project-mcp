from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import PluginRegistry, builtin_registry
from project_mcp.plugins.rust.analyzer import RustAnalyzer
from project_mcp.plugins.rust.descriptor import DESCRIPTOR

LIB = """\
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    #[test]
    fn adds() {}
}
"""


class _RustBeforeTestDiscovery(RustAnalyzer):
    """The Rust plugin as released before it recorded test functions."""

    link_test_evidence = None


def test_upgrading_records_the_tests_of_rust_files_indexed_before_test_discovery(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)
    old_registry = PluginRegistry()
    old_registry.register(
        replace(DESCRIPTOR, version="0.1.0", analyzer=f"{__name__}:_RustBeforeTestDiscovery")
    )
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=old_registry)
    assert conn.execute("SELECT COUNT(*) FROM tests").fetchone() == (0,)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())

    recorded = conn.execute(
        "SELECT s.qualified_name FROM tests t JOIN symbols s ON s.id = t.symbol_id"
    ).fetchall()
    conn.close()
    assert recorded == [("src.lib.tests.adds",)]
