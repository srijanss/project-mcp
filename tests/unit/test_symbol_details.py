from project_mcp.tools.symbol_details import MAX_SOURCE_LINES, describe_symbol

MODELS = (
    "import os\n"
    "\n"
    "\n"
    "class Widget:\n"
    '    """A widget."""\n'
    "\n"
    "    def size(self):\n"
    "        return 1\n"
    "\n"
    "\n"
    "class Other:\n"
    "    pass\n"
)


def _project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(MODELS)
    return tmp_path


def test_describe_symbol_includes_the_symbols_own_source(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.models.Widget")

    assert details["found"] is True
    assert details["symbol"]["qualified_name"] == "app.models.Widget"
    assert details["source"].startswith("class Widget:")
    assert "def size(self):" in details["source"]
    assert "class Other" not in details["source"]
    assert details["source_truncated"] is False


def test_describe_symbol_cuts_long_source_and_says_so(tmp_path):
    (tmp_path / "app").mkdir()
    body = "".join(f"    x{i} = {i}\n" for i in range(300))
    (tmp_path / "app" / "long.py").write_text("def big():\n" + body)

    details = describe_symbol(tmp_path, "app.long.big")

    assert details["source_truncated"] is True
    assert len(details["source"].splitlines()) == MAX_SOURCE_LINES
    assert details["source_total_lines"] == 301
    assert details["source"].startswith("def big():")


def test_describe_symbol_lists_direct_callers_and_callees(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "flow.py").write_text(
        "def leaf():\n    return 1\n\n\n"
        "def middle():\n    return leaf()\n\n\n"
        "def top():\n    return middle()\n"
    )

    details = describe_symbol(tmp_path, "app.flow.middle")

    assert [c["symbol"] for c in details["callers"]] == ["app.flow.top"]
    assert [c["symbol"] for c in details["callees"]] == ["app.flow.leaf"]
    assert details["callers"][0]["confidence"] == "high"


def test_describe_symbol_lists_tests_covering_its_module(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("def value():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import value\n\n\ndef test_value():\n    assert value()\n"
    )

    details = describe_symbol(tmp_path, "app.models.value")

    assert details["tests"] == [
        {
            "test_file": "tests/test_models.py",
            "confidence": "high",
            "evidence": ["direct_import"],
            "scope": "module",
        }
    ]


def test_describe_symbol_reports_missing_symbols(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.models.Nope")

    assert details == {"found": False, "symbol": None}
