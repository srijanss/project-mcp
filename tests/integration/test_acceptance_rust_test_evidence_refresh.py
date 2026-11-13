import sys

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.rust import analyzer, tree_parser

LIB = """\
#[cfg(test)]
mod tests {
    #[test]
    fn kept() {}

    #[test]
    fn demoted() {}

    #[test]
    fn deleted() {}
}
"""

LIB_AFTER = """\
#[cfg(test)]
mod tests {
    #[test]
    fn kept() {}

    fn demoted() {}
}
"""

OTHER = "#[test]\nfn untouched() {}\n"


def _scan(project):
    conn = get_connection(project)
    run_scan(conn, project, load_config(project))
    recorded = sorted(
        name
        for (name,) in conn.execute(
            "SELECT s.qualified_name FROM tests t JOIN symbols s ON s.id = t.symbol_id"
        )
    )
    conn.close()
    return recorded


def _project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "other.rs").write_text(OTHER)
    return tmp_path


def test_reindexing_drops_tests_that_were_removed_or_lost_their_attribute(tmp_path):
    project = _project(tmp_path)
    assert _scan(project) == [
        "src.lib.tests.deleted",
        "src.lib.tests.demoted",
        "src.lib.tests.kept",
        "tests.other.untouched",
    ]

    (project / "src" / "lib.rs").write_text(LIB_AFTER)

    assert _scan(project) == ["src.lib.tests.kept", "tests.other.untouched"]


def test_reindexing_without_tree_sitter_clears_tests_it_can_no_longer_read(tmp_path, monkeypatch):
    project = _project(tmp_path)
    assert len(_scan(project)) == 4

    monkeypatch.setitem(sys.modules, "tree_sitter_rust", None)
    monkeypatch.setattr(analyzer, "parse_rust_tree", None)
    monkeypatch.setattr(analyzer, "discover_rust_tests", None)
    monkeypatch.setattr(tree_parser, "discover_rust_tests", None)

    assert _scan(project) == []
