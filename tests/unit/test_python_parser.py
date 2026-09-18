from project_mcp.analyzers.python.parser import extract_imports, parse_python_source

SOURCE = '''"""Module docstring."""


def top_level(x):
    return x


class Widget:
    def render(self):
        return "ok"

    def _internal(self):
        pass
'''


def test_parse_python_source_extracts_module_function_class_and_method():
    symbols = parse_python_source("app/widget.py", SOURCE)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    module_symbol = by_qualified_name["app.widget"]
    assert module_symbol["kind"] == "module"
    assert module_symbol["name"] == "app.widget"
    assert module_symbol["visibility"] == "public"

    func_symbol = by_qualified_name["app.widget.top_level"]
    assert func_symbol["kind"] == "function"
    assert func_symbol["name"] == "top_level"
    assert func_symbol["visibility"] == "public"
    assert func_symbol["start_line"] == 4

    class_symbol = by_qualified_name["app.widget.Widget"]
    assert class_symbol["kind"] == "class"
    assert class_symbol["name"] == "Widget"

    method_symbol = by_qualified_name["app.widget.Widget.render"]
    assert method_symbol["kind"] == "method"
    assert method_symbol["name"] == "render"
    assert method_symbol["visibility"] == "public"

    private_method = by_qualified_name["app.widget.Widget._internal"]
    assert private_method["kind"] == "method"
    assert private_method["visibility"] == "private"


def test_parse_python_source_returns_error_marker_for_syntax_error():
    result = parse_python_source("app/broken.py", "def broken(:\n    pass\n")

    assert len(result) == 1
    assert result[0]["kind"] == "parse_error"
    assert result[0]["path"] == "app/broken.py"
    assert result[0]["error"]


def test_extract_imports_extracts_absolute_and_relative_imports():
    source = (
        "import os\n"
        "import json as j\n"
        "from app.models import Widget, Gadget as G\n"
        "from . import utils\n"
        "from ..pkg import helper\n"
    )

    imports = extract_imports("app/service.py", source)
    by_line = {imp["line"]: imp for imp in imports}

    assert by_line[1] == {"module": "os", "names": [], "level": 0, "line": 1}
    assert by_line[2] == {"module": "json", "names": [], "level": 0, "line": 2}
    assert by_line[3] == {
        "module": "app.models",
        "names": ["Widget", "Gadget"],
        "level": 0,
        "line": 3,
    }
    assert by_line[4] == {"module": None, "names": ["utils"], "level": 1, "line": 4}
    assert by_line[5] == {"module": "pkg", "names": ["helper"], "level": 2, "line": 5}


def test_parse_python_source_extracts_class_bases():
    source = (
        "class Base:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Mixin:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Widget(Base, pkg.mod.Other, Mixin):\n"
        "    pass\n"
    )

    symbols = parse_python_source("app/widget.py", source)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    assert by_qualified_name["app.widget.Base"]["bases"] == []
    assert by_qualified_name["app.widget.Widget"]["bases"] == [
        "Base",
        "pkg.mod.Other",
        "Mixin",
    ]


def test_extract_imports_marks_wildcard_import_as_dynamic():
    imports = extract_imports("app/service.py", "from app.utils import *\n")

    assert imports == [
        {
            "module": "app.utils",
            "names": [],
            "level": 0,
            "line": 1,
            "dynamic": True,
        }
    ]


def test_parse_python_source_marks_dynamically_computed_base_as_limitation():
    source = "class Widget(make_base()):\n    pass\n"

    symbols = parse_python_source("app/widget.py", source)
    widget = next(s for s in symbols if s["qualified_name"] == "app.widget.Widget")

    assert widget["bases"] == [{"dynamic": True, "expression": "make_base()"}]
