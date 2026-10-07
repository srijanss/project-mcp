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
    assert analysis.symbol_edges == [
        ("src.lib.Widget", "src.lib.Describe", "implements"),
        ("src.lib.Missing", "src.lib.Describe", "implements"),
    ]
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
