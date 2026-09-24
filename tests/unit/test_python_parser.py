from project_mcp.analyzers.python.parser import (
    analyze_python_source,
    extract_attribute_calls,
    extract_foreign_attribute_accesses,
    extract_imports,
    extract_name_loads,
    extract_self_attribute_references,
    extract_static_calls,
    parse_python_source,
)

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


def test_parse_python_source_extracts_class_level_fields():
    source = (
        "class Payment:\n"
        "    status = 'new'\n"
        "    amount: int = 0\n"
        "    note: str\n"
        "    _secret = None\n"
        "\n"
        "    def run(self):\n"
        "        local = 1\n"
    )

    symbols = parse_python_source("app/payment.py", source)
    fields = {s["qualified_name"]: s for s in symbols if s["kind"] == "field"}

    assert set(fields) == {
        "app.payment.Payment.status",
        "app.payment.Payment.amount",
        "app.payment.Payment.note",
        "app.payment.Payment._secret",
    }
    assert fields["app.payment.Payment.status"]["name"] == "status"
    assert fields["app.payment.Payment.status"]["start_line"] == 2
    assert fields["app.payment.Payment._secret"]["visibility"] == "private"


def test_extract_self_attribute_references_finds_self_accesses_in_methods():
    source = (
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self, other):\n"
        "        if self.status == 'new':\n"
        "            self.amount = 1\n"
        "        return other.status\n"
        "\n"
        "def helper(self):\n"
        "    return self.status\n"
    )

    refs = extract_self_attribute_references("app/payment.py", source)

    assert refs == [
        {
            "referrer": "app.payment.Payment.run",
            "class": "app.payment.Payment",
            "attribute": "status",
            "line": 5,
        },
        {
            "referrer": "app.payment.Payment.run",
            "class": "app.payment.Payment",
            "attribute": "amount",
            "line": 6,
        },
    ]


def test_extract_foreign_attribute_accesses_finds_non_self_accesses_in_functions():
    source = (
        "def report(payment, other):\n"
        "    total = payment.amount\n"
        "    other.status = 'x'\n"
        "    return self_like.note\n"
        "\n"
        "\n"
        "class Handler:\n"
        "    def run(self, payment):\n"
        "        return self.helper() + payment.amount\n"
        "\n"
        "\n"
        "unrelated = config.debug\n"
    )

    accesses = extract_foreign_attribute_accesses("app/report.py", source)

    assert accesses == [
        {"referrer": "app.report.report", "attribute": "amount", "line": 2},
        {"referrer": "app.report.report", "attribute": "status", "line": 3},
        {"referrer": "app.report.report", "attribute": "note", "line": 4},
        {"referrer": "app.report.Handler.run", "attribute": "amount", "line": 9},
    ]


def test_parse_python_source_extracts_module_level_upper_case_constants():
    source = (
        "MAX_RETRIES = 3\n"
        "TIMEOUT: float = 1.5\n"
        "_PRIVATE_LIMIT = 9\n"
        "logger = get_logger()\n"
        "\n"
        "def run():\n"
        "    LOCAL_CAP = 2\n"
    )

    symbols = parse_python_source("app/settings.py", source)
    constants = {s["qualified_name"]: s for s in symbols if s["kind"] == "constant"}

    assert set(constants) == {
        "app.settings.MAX_RETRIES",
        "app.settings.TIMEOUT",
        "app.settings._PRIVATE_LIMIT",
    }
    assert constants["app.settings.MAX_RETRIES"]["start_line"] == 1
    assert constants["app.settings._PRIVATE_LIMIT"]["visibility"] == "private"


def test_extract_name_loads_finds_bare_names_read_inside_functions():
    source = (
        "LIMIT = 3\n"
        "TOP = LIMIT\n"
        "\n"
        "\n"
        "def run(x):\n"
        "    total = LIMIT + x\n"
        "    LIMIT_LOCAL = 1\n"
        "    return helper(total)\n"
    )

    loads = extract_name_loads("app/job.py", source)

    assert loads == [
        {"referrer": "app.job.run", "name": "LIMIT", "line": 6},
        {"referrer": "app.job.run", "name": "x", "line": 6},
        {"referrer": "app.job.run", "name": "helper", "line": 8},
        {"referrer": "app.job.run", "name": "total", "line": 8},
    ]


ANALYSIS_SOURCE = (
    "import app.helpers as h\n"
    "from app.settings import LIMIT\n"
    "\n"
    "MAX = 3\n"
    "\n"
    "\n"
    "class Payment:\n"
    "    status = 'new'\n"
    "\n"
    "    def run(self, other):\n"
    "        h.helper(self.status, other.amount)\n"
    "        return local(LIMIT, MAX)\n"
    "\n"
    "\n"
    "def local(a, b):\n"
    "    return a + b\n"
)


def test_analyze_python_source_matches_each_extractor_with_one_parse(monkeypatch):
    import ast

    path = "app/payment.py"
    expected = {
        "symbols": parse_python_source(path, ANALYSIS_SOURCE),
        "imports": extract_imports(path, ANALYSIS_SOURCE),
        "calls": extract_static_calls(path, ANALYSIS_SOURCE),
        "attribute_calls": extract_attribute_calls(path, ANALYSIS_SOURCE),
        "self_references": extract_self_attribute_references(path, ANALYSIS_SOURCE),
        "foreign_accesses": extract_foreign_attribute_accesses(path, ANALYSIS_SOURCE),
        "name_loads": extract_name_loads(path, ANALYSIS_SOURCE),
    }
    parses = []
    original_parse = ast.parse

    def counting_parse(*args, **kwargs):
        parses.append(1)
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(ast, "parse", counting_parse)

    assert analyze_python_source(path, ANALYSIS_SOURCE) == expected
    assert len(parses) == 1


def test_analyze_python_source_reports_syntax_error_with_empty_extractions():
    analysis = analyze_python_source("app/broken.py", "def broken(:\n    pass\n")

    assert analysis["symbols"][0]["kind"] == "parse_error"
    assert {key: value for key, value in analysis.items() if key != "symbols"} == {
        "imports": [],
        "calls": [],
        "attribute_calls": [],
        "self_references": [],
        "foreign_accesses": [],
        "name_loads": [],
    }


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
    assert by_line[2] == {
        "module": "json",
        "names": [],
        "level": 0,
        "line": 2,
        "aliases": {"j": "json"},
    }
    assert by_line[3] == {
        "module": "app.models",
        "names": ["Widget", "Gadget"],
        "level": 0,
        "line": 3,
        "aliases": {"G": "Gadget"},
    }
    assert by_line[4] == {"module": None, "names": ["utils"], "level": 1, "line": 4}
    assert by_line[5] == {"module": "pkg", "names": ["helper"], "level": 2, "line": 5}


def test_extract_imports_records_aliases_for_from_imports():
    source = (
        "from app.helpers import helper as do_help, MAX_RETRIES\n"
        "from app.models import Widget\n"
    )

    imports = extract_imports("app/service.py", source)

    assert imports == [
        {
            "module": "app.helpers",
            "names": ["helper", "MAX_RETRIES"],
            "level": 0,
            "line": 1,
            "aliases": {"do_help": "helper"},
        },
        {"module": "app.models", "names": ["Widget"], "level": 0, "line": 2},
    ]


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


def test_extract_static_calls_returns_same_module_function_calls():
    source = (
        "def helper():\n"
        "    return 'done'\n"
        "\n"
        "\n"
        "def run():\n"
        "    return helper()\n"
    )

    assert extract_static_calls("app/workflow.py", source) == [
        {
            "caller": "app.workflow.run",
            "callee": "helper",
            "line": 6,
        }
    ]


def test_extract_attribute_calls_records_dotted_object_and_attribute():
    source = (
        "import app.helpers\n"
        "\n"
        "\n"
        "def run(thing):\n"
        "    app.helpers.helper()\n"
        "    thing.save()\n"
        "    make().go()\n"
        "    return plain()\n"
        "\n"
        "\n"
        "app.helpers.setup()\n"
    )

    assert extract_attribute_calls("app/service.py", source) == [
        {
            "caller": "app.service.run",
            "object": "app.helpers",
            "attribute": "helper",
            "line": 5,
        },
        {
            "caller": "app.service.run",
            "object": "thing",
            "attribute": "save",
            "line": 6,
        },
    ]


def test_extract_static_calls_qualifies_method_callers_with_their_class():
    source = (
        "class Service:\n"
        "    def run(self):\n"
        "        return helper()\n"
    )

    assert extract_static_calls("app/workflow.py", source) == [
        {
            "caller": "app.workflow.Service.run",
            "callee": "helper",
            "line": 3,
        }
    ]


def test_parse_python_source_extracts_nested_function():
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "\n"
        "    return inner\n"
    )

    symbols = parse_python_source("app/workflow.py", source)
    nested = next(
        symbol
        for symbol in symbols
        if symbol["qualified_name"] == "app.workflow.outer.inner"
    )

    assert nested["kind"] == "function"
    assert nested["start_line"] == 2
