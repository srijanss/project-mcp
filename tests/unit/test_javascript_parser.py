from project_mcp.analyzers.javascript.parser import (
    extract_js_exports,
    extract_js_imports,
    parse_js_source,
)

SOURCE = """
function topLevel(x) {
  return x;
}

class Widget {
  render() {
    return "ok";
  }

  _internal() {
    return null;
  }
}
"""


def test_parse_js_source_extracts_module_function_class_and_method():
    symbols = parse_js_source("app/widget.js", SOURCE)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    module_symbol = by_qualified_name["app.widget"]
    assert module_symbol["kind"] == "module"
    assert module_symbol["name"] == "app.widget"

    func_symbol = by_qualified_name["app.widget.topLevel"]
    assert func_symbol["kind"] == "function"
    assert func_symbol["name"] == "topLevel"
    assert func_symbol["visibility"] == "public"

    class_symbol = by_qualified_name["app.widget.Widget"]
    assert class_symbol["kind"] == "class"
    assert class_symbol["name"] == "Widget"

    method_symbol = by_qualified_name["app.widget.Widget.render"]
    assert method_symbol["kind"] == "method"
    assert method_symbol["name"] == "render"


def test_extract_js_imports_extracts_es_module_imports():
    source = (
        "import React from 'react';\n"
        "import { useState, useEffect } from 'react';\n"
        "import './styles.css';\n"
    )

    imports = extract_js_imports("app/widget.js", source)
    by_line = {imp["line"]: imp for imp in imports}

    assert by_line[1] == {
        "module": "react",
        "names": [],
        "default": "React",
        "line": 1,
    }
    assert by_line[2] == {
        "module": "react",
        "names": ["useState", "useEffect"],
        "default": None,
        "line": 2,
    }
    assert by_line[3] == {
        "module": "./styles.css",
        "names": [],
        "default": None,
        "line": 3,
    }


def test_parse_js_source_detects_function_component_returning_jsx():
    source = (
        "function Widget(props) {\n"
        "  return <div>{props.label}</div>;\n"
        "}\n"
        "\n"
        "function helper(x) {\n"
        "  return x + 1;\n"
        "}\n"
    )

    symbols = parse_js_source("app/Widget.js", source)
    by_name = {s["name"]: s for s in symbols}

    assert by_name["Widget"]["kind"] == "component"
    assert by_name["helper"]["kind"] == "function"


def test_parse_js_source_detects_arrow_component_returning_jsx():
    source = (
        "const Widget = (props) => {\n"
        "  return (\n"
        "    <div>{props.label}</div>\n"
        "  );\n"
        "};\n"
    )

    symbols = parse_js_source("app/Widget.js", source)
    by_name = {s["name"]: s for s in symbols}

    assert by_name["Widget"]["kind"] == "component"
    assert by_name["Widget"]["qualified_name"] == "app.Widget.Widget"


def test_extract_js_exports_extracts_named_and_default_exports():
    source = (
        "export function topLevel(x) { return x; }\n"
        "export class Widget {}\n"
        "export const value = 1;\n"
        "export default Widget;\n"
    )

    exports = extract_js_exports("app/widget.js", source)
    by_line = {exp["line"]: exp for exp in exports}

    assert by_line[1] == {"name": "topLevel", "kind": "named", "line": 1}
    assert by_line[2] == {"name": "Widget", "kind": "named", "line": 2}
    assert by_line[3] == {"name": "value", "kind": "named", "line": 3}
    assert by_line[4] == {"name": "Widget", "kind": "default", "line": 4}


def test_extract_js_exports_extracts_named_export_list():
    source = "const a = 1;\nconst b = 2;\nexport { a, b };\n"

    exports = extract_js_exports("app/widget.js", source)

    assert exports == [
        {"name": "a", "kind": "named", "line": 3},
        {"name": "b", "kind": "named", "line": 3},
    ]


def test_parse_js_source_detects_async_arrow_component_returning_jsx():
    source = (
        "const Widget = async (props) => {\n"
        "  return (\n"
        "    <div>{props.label}</div>\n"
        "  );\n"
        "};\n"
    )

    symbols = parse_js_source("app/Widget.js", source)
    by_name = {s["name"]: s for s in symbols}

    assert by_name["Widget"]["kind"] == "component"
    assert by_name["Widget"]["qualified_name"] == "app.Widget.Widget"


def test_parse_js_source_does_not_treat_commented_jsx_return_as_component():
    source = (
        "function HelperUtil(x) {\n"
        "  // return <div>{x}</div>;\n"
        "  return x + 1;\n"
        "}\n"
    )

    symbols = parse_js_source("app/helper.js", source)
    by_name = {s["name"]: s for s in symbols}

    assert by_name["HelperUtil"]["kind"] == "function"


def test_extract_js_exports_extracts_multiline_export_list():
    source = "const a = 1;\nconst b = 2;\nexport {\n  a,\n  b\n};\n"

    exports = extract_js_exports("app/widget.js", source)

    assert exports == [
        {"name": "a", "kind": "named", "line": 3},
        {"name": "b", "kind": "named", "line": 3},
    ]


def test_extract_js_imports_marks_backtick_dynamic_import_and_require_as_dynamic():
    source = (
        "const mod = require(`./mod`);\n"
        "import(`./lazy`).then(m => m.default());\n"
    )

    imports = extract_js_imports("app/widget.js", source)
    by_line = {imp["line"]: imp for imp in imports}

    assert by_line[1] == {
        "module": "./mod",
        "names": [],
        "default": None,
        "line": 1,
        "dynamic": True,
    }
    assert by_line[2] == {
        "module": "./lazy",
        "names": [],
        "default": None,
        "line": 2,
        "dynamic": True,
    }


def test_extract_js_imports_marks_dynamic_import_and_require_conservatively():
    source = (
        "const mod = require('./mod');\n"
        "import('./lazy').then(m => m.default());\n"
    )

    imports = extract_js_imports("app/widget.js", source)
    by_line = {imp["line"]: imp for imp in imports}

    assert by_line[1] == {
        "module": "./mod",
        "names": [],
        "default": None,
        "line": 1,
        "dynamic": True,
    }
    assert by_line[2] == {
        "module": "./lazy",
        "names": [],
        "default": None,
        "line": 2,
        "dynamic": True,
    }
