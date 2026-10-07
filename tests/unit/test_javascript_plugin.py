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
