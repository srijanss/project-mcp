from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import PluginRegistry, builtin_registry
from project_mcp.plugins.rust.analyzer import RustAnalyzer
from project_mcp.plugins.rust.descriptor import DESCRIPTOR
from project_mcp.tools.tests import get_tests_for

LIB = """\
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds() {
        assert_eq!(add(1, 1), 2);
    }
}
"""


class _RustBeforeCallEdges(RustAnalyzer):
    """The Rust plugin as released before it linked calls and `use` references."""

    link_cross_file = None


def test_upgrading_links_the_tests_of_rust_files_indexed_before_call_edges(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)
    old_registry = PluginRegistry()
    old_registry.register(
        replace(DESCRIPTOR, version="0.2.0", analyzer=f"{__name__}:_RustBeforeCallEdges")
    )
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=old_registry)
    calls = "SELECT COUNT(*) FROM relationships WHERE relationship_type = 'calls'"
    assert conn.execute(calls).fetchone() == (0,)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    conn.close()

    assert [row["tests"] for row in get_tests_for(tmp_path, "src.lib.add")] == [["src.lib.tests.adds"]]
