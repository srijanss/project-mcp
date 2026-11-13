import sys

from project_mcp.plugins.rust import analyzer
from project_mcp.plugins.rust.analyzer import RustAnalyzer

LIB_SOURCE = """use crate::shapes;
use std::fmt::Display;

pub trait Describe {}
pub struct Widget;
struct Gadget;
impl Describe for Widget {}
impl Gadget {}
impl Describe for Missing {}
"""


def test_analyze_returns_symbols_trait_impls_and_use_paths():
    analysis = RustAnalyzer().analyze("src/lib.rs", LIB_SOURCE)

    assert [(s["qualified_name"], s["kind"]) for s in analysis.symbols] == [
        ("src.lib", "module"),
        ("src.lib.Describe", "trait"),
        ("src.lib.Widget", "struct"),
        ("src.lib.Gadget", "struct"),
    ]
    assert analysis.symbol_edges == [("src.lib.Widget", "src.lib.Describe", "implements")]
    assert analysis.imports == ["crate", "std::fmt"]


def test_resolve_import_maps_crate_paths_to_candidate_files():
    analyzer = RustAnalyzer()

    assert analyzer.resolve_import("app/src/main.rs", "crate") == [
        "app/src/lib.rs",
        "app/src/main.rs",
    ]
    assert analyzer.resolve_import("app/src/main.rs", "crate::shapes::square") == [
        "app/src/shapes/square.rs",
        "app/src/shapes/square/mod.rs",
    ]
    assert analyzer.resolve_import("app/src/main.rs", "std::fmt") == []
    assert analyzer.resolve_import("build.rs", "crate::shapes") == []


def test_is_test_file_recognises_test_dirs_and_test_name_affixes():
    from pathlib import Path

    analyzer = RustAnalyzer()

    assert [
        analyzer.is_test_file(Path(path))
        for path in (
            "tests/integration.rs",
            "src/test/helpers.rs",
            "src/test_widget.rs",
            "src/widget_test.rs",
            "src/widget.rs",
            "src/testing.rs",
        )
    ] == [True, True, True, True, False, False]


def test_builtin_registry_serves_the_rust_analyzer():
    from project_mcp.plugins.registry import builtin_registry

    assert isinstance(builtin_registry().analyzer_for("rust"), RustAnalyzer)


def test_analyze_parses_symbols_with_tree_sitter(monkeypatch):
    monkeypatch.setattr(analyzer, "parse_rust_tree", lambda path, source: [{"qualified_name": "tree"}])

    rust = RustAnalyzer()
    symbols = rust.analyze("src/lib.rs", LIB_SOURCE).symbols

    assert (rust.backend, rust.warnings) == ("tree-sitter", [])
    assert symbols == [{"qualified_name": "tree"}]


def test_analyze_falls_back_to_the_regex_parser_without_tree_sitter(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_rust", None)
    monkeypatch.setattr(analyzer, "parse_rust_tree", None)

    rust = RustAnalyzer()
    symbols = rust.analyze("src/lib.rs", LIB_SOURCE).symbols

    assert rust.backend == "regex"
    assert rust.warnings == [
        "falls back to its regex parser: tree_sitter_rust is not installed"
        " (import of tree_sitter_rust halted; None in sys.modules)"
    ]
    assert [s["name"] for s in symbols] == ["src.lib", "Describe", "Widget", "Gadget"]


def test_analyze_links_multiline_generic_trait_impls():
    source = "pub trait Describe {}\npub struct Wrapper<T>(T);\nimpl<T>\n    Describe for Wrapper<T>\nwhere\n    T: Clone,\n{}\n"

    analysis = RustAnalyzer().analyze("src/lib.rs", source)

    assert analysis.symbol_edges == [("src.lib.Wrapper", "src.lib.Describe", "implements")]


def test_link_test_evidence_records_each_test_function_once_against_its_symbol(tmp_path):
    from project_mcp.config import load_config
    from project_mcp.db import get_connection
    from project_mcp.indexer import run_scan
    from project_mcp.plugins.analysis import ChangedFile, LinkContext

    source = "pub fn add() {}\n\n#[cfg(test)]\nmod tests {\n    fn helper() {}\n\n    #[test]\n    fn adds() {}\n}\n"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(source)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    path_to_file_id = dict(conn.execute("SELECT path, id FROM files"))
    rust = RustAnalyzer()
    context = LinkContext(
        conn=conn,
        project_root=tmp_path,
        source_roots=[],
        path_to_file_id=path_to_file_id,
        changed={"src/lib.rs": ChangedFile(path_to_file_id["src/lib.rs"], source, rust.analyze("src/lib.rs", source))},
        added=set(),
        plugin_paths=["src/lib.rs"],
    )

    rust.link_test_evidence(context)
    rust.link_test_evidence(context)

    recorded = conn.execute(
        """
        SELECT s.qualified_name, t.test_kind, t.framework FROM tests t
        JOIN symbols s ON s.id = t.symbol_id
        """
    ).fetchall()
    conn.close()
    assert recorded == [("src.lib.tests.adds", "test_function", "cargo")]


def test_descriptor_version_is_past_the_release_without_test_discovery():
    """Files indexed by 0.1.0 never had their tests recorded; a new version re-indexes them."""
    from project_mcp.plugins.rust.descriptor import DESCRIPTOR

    assert tuple(int(part) for part in DESCRIPTOR.version.split(".")) > (0, 1, 0)


def test_link_test_evidence_ignores_a_method_sharing_the_test_s_qualified_name(tmp_path):
    from project_mcp.config import load_config
    from project_mcp.db import get_connection
    from project_mcp.indexer import run_scan
    from project_mcp.plugins.analysis import ChangedFile, LinkContext

    source = "mod tests {\n    impl Fixture {\n        fn adds(&self) {}\n    }\n\n    #[test]\n    fn adds() {}\n}\n"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(source)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    file_id = conn.execute("SELECT id FROM files WHERE path = 'src/lib.rs'").fetchone()[0]
    rust = RustAnalyzer()

    rust.link_test_evidence(
        LinkContext(
            conn=conn,
            project_root=tmp_path,
            source_roots=[],
            path_to_file_id={"src/lib.rs": file_id},
            changed={"src/lib.rs": ChangedFile(file_id, source, rust.analyze("src/lib.rs", source))},
            added=set(),
            plugin_paths=["src/lib.rs"],
        )
    )

    recorded = conn.execute(
        "SELECT s.start_line FROM tests t JOIN symbols s ON s.id = t.symbol_id"
    ).fetchall()
    conn.close()
    assert recorded == [(7,)]


def test_link_cross_file_links_calls_and_use_references_and_keeps_them_when_the_callee_is_reindexed(tmp_path):
    from project_mcp.config import load_config
    from project_mcp.db import get_connection
    from project_mcp.indexer import run_scan

    (tmp_path / "Cargo.toml").write_text('[package]\nname = "my-crate"\nversion = "0.1.0"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub struct Widget;\n\npub fn add() {}\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "it.rs").write_text(
        "use my_crate::Widget;\n\n#[test]\nfn uses() {\n    my_crate::add();\n    let _w: Widget = Widget;\n}\n"
    )

    def edges():
        return set(
            conn.execute(
                """
                SELECT source.qualified_name, target.qualified_name, r.relationship_type, r.confidence
                FROM relationships r
                JOIN symbols source ON source.id = r.source_entity_id
                JOIN symbols target ON target.id = r.target_entity_id
                WHERE r.relationship_type IN ('calls', 'references')
                """
            )
        )

    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    expected = {
        ("tests.it.uses", "src.lib.add", "calls", "high"),
        ("tests.it.uses", "src.lib.Widget", "references", "high"),
    }
    assert edges() == expected

    (tmp_path / "src" / "lib.rs").write_text("pub struct Widget;\n\n\npub fn add() {}\n")
    run_scan(conn, tmp_path, load_config(tmp_path))
    try:
        assert edges() == expected
    finally:
        conn.close()


def test_descriptor_version_is_past_the_release_without_call_edges():
    """Files indexed by 0.2.0 have no calls/references edges; a new version re-indexes them."""
    from project_mcp.plugins.rust.descriptor import DESCRIPTOR

    assert tuple(int(part) for part in DESCRIPTOR.version.split(".")) > (0, 2, 0)
