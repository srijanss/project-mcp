import sys

import pytest

from project_mcp.plugins.javascript import analyzer
from project_mcp.plugins.javascript.analyzer import JavaScriptAnalyzer

SOURCE = """import React from 'react';
import { helper } from './util';
const lazy = import('./lazy');
const legacy = require('./legacy');

export function Widget() {
  return <div />;
}
"""


def test_analyze_returns_symbols_and_static_import_modules():
    analysis = JavaScriptAnalyzer().analyze("src/Widget.jsx", SOURCE)

    assert [(s["qualified_name"], s["kind"]) for s in analysis.symbols] == [
        ("src.Widget", "module"),
        ("src.Widget.Widget", "component"),
    ]
    assert analysis.symbol_edges == []
    assert analysis.imports == ["react", "./util"]


def test_resolve_import_maps_relative_modules_to_js_and_ts_candidates():
    analyzer = JavaScriptAnalyzer()

    assert analyzer.resolve_import("src/app/main.ts", "../util") == [
        "src/util.js",
        "src/util.jsx",
        "src/util.ts",
        "src/util.tsx",
        "src/util/index.js",
        "src/util/index.jsx",
        "src/util/index.ts",
        "src/util/index.tsx",
    ]
    assert analyzer.resolve_import("src/app/main.ts", "react") == []


def test_is_test_file_recognises_test_dirs_and_test_spec_suffixes():
    from pathlib import Path

    analyzer = JavaScriptAnalyzer()

    assert [
        analyzer.is_test_file(Path(path))
        for path in (
            "tests/widget.js",
            "src/__tests__/Widget.tsx",
            "src/Widget.test.tsx",
            "src/widget.spec.ts",
            "src/Widget.tsx",
            "src/test_widget.js",
        )
    ] == [True, True, True, True, False, False]


def test_builtin_registry_serves_one_javascript_analyzer_for_js_and_ts():
    from project_mcp.plugins.registry import builtin_registry

    registry = builtin_registry()

    assert isinstance(registry.analyzer_for("javascript"), JavaScriptAnalyzer)
    assert registry.analyzer_for("typescript") is registry.analyzer_for("javascript")


@pytest.mark.parametrize(
    ("path", "grammar"),
    [("a.js", "javascript"), ("a.jsx", "tsx"), ("a.ts", "typescript"), ("a.tsx", "tsx")],
)
def test_analyze_parses_with_the_grammar_for_the_file_suffix(path, grammar, monkeypatch):
    grammars = []
    monkeypatch.setattr(
        analyzer, "parse_js_tree", lambda p, source, g: grammars.append(g) or []
    )

    js = JavaScriptAnalyzer()
    js.analyze(path, "")

    assert js.backend == "tree-sitter"
    assert js.warnings == []
    assert grammars == [grammar]


def test_analyze_falls_back_to_the_regex_parser_without_tree_sitter(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_typescript", None)
    monkeypatch.setattr(analyzer, "parse_js_tree", None)

    js = JavaScriptAnalyzer()
    symbols = js.analyze("src/Widget.tsx", SOURCE).symbols

    assert js.backend == "regex"
    assert js.warnings == [
        "falls back to its regex parser: tree_sitter_typescript is not installed"
        " (import of tree_sitter_typescript halted; None in sys.modules)"
    ]
    assert [s["kind"] for s in symbols] == ["module", "component"]
