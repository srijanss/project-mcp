from project_mcp.tools.symbol_details import describe_symbol

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


def test_describe_symbol_reports_missing_symbols(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.models.Nope")

    assert details == {"found": False, "symbol": None}
