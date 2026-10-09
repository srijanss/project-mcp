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


def test_describe_symbol_leaves_test_functions_out_of_callers(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "flow.py").write_text(
        "def middle():\n    return 1\n\n\ndef top():\n    return middle()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_flow.py").write_text(
        "from app.flow import middle\n\n\ndef test_middle():\n    assert middle()\n"
    )

    details = describe_symbol(tmp_path, "app.flow.middle")

    assert [c["symbol"] for c in details["callers"]] == ["app.flow.top"]
    assert details["tests"][0]["test_file"] == "tests/test_flow.py"


def test_describe_symbol_lists_tests_covering_its_module(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("def value():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import value\n\n\ndef test_imports_only():\n    assert True\n"
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


def test_describe_symbol_prefers_the_tests_that_reference_it_by_name(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("def value():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import value\n\n\ndef test_value():\n    assert value()\n"
    )
    (tmp_path / "tests" / "test_other.py").write_text(
        "from app.models import value\n\n\ndef test_imports_only():\n    assert True\n"
    )

    details = describe_symbol(tmp_path, "app.models.value")

    assert details["tests"] == [
        {
            "test_file": "tests/test_models.py",
            "confidence": "high",
            "evidence": ["symbol_reference"],
            "tests": ["tests.test_models.test_value"],
            "scope": "symbol",
        }
    ]


def test_describe_symbol_resolves_a_unique_short_name(tmp_path):
    details = describe_symbol(_project(tmp_path), "Widget")

    assert details["found"] is True
    assert details["symbol"]["qualified_name"] == "app.models.Widget"
    assert details["source"].startswith("class Widget:")


def test_describe_symbol_lists_candidates_for_an_ambiguous_short_name(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("class Widget:\n    pass\n")
    (tmp_path / "app" / "b.py").write_text("class Widget:\n    pass\n")

    details = describe_symbol(tmp_path, "Widget")

    assert details["found"] is False
    assert details["candidates"] == ["app.a.Widget", "app.b.Widget"]


def test_describe_symbol_reports_missing_symbols(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.models.Nope")

    assert details == {"found": False, "symbol": None}


def test_describe_symbol_reports_unavailable_source_when_the_file_is_gone(
    tmp_path, monkeypatch
):
    context = {
        "found": True,
        "symbol": {
            "name": "gone",
            "qualified_name": "app.gone.gone",
            "kind": "function",
            "start_line": 1,
            "end_line": 2,
            "file": "app/gone.py",
        },
    }
    monkeypatch.setattr(
        "project_mcp.tools.symbol_details._resolve", lambda *a, **k: context
    )

    details = describe_symbol(tmp_path, "app.gone.gone")

    assert details["found"] is True
    assert details["source"] is None
    assert details["source_error"] == "FileNotFoundError"
    assert details["source_truncated"] is False
    assert details["source_total_lines"] == 0


def test_describe_symbol_suggests_close_matches_when_the_name_is_not_found(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.wrong.Widget")

    assert details["found"] is False
    assert details["symbol"] is None
    assert details["suggestions"] == ["app.models.Widget"]


def test_describe_symbol_limits_how_many_suggestions_it_returns(tmp_path):
    (tmp_path / "app").mkdir()
    classes = "".join(f"class Widget{letter}:\n    pass\n\n\n" for letter in "ABCDEFGH")
    (tmp_path / "app" / "models.py").write_text(classes)

    details = describe_symbol(tmp_path, "app.wrong.Widget")

    assert details["found"] is False
    assert len(details["suggestions"]) == 5


def _big_class(tmp_path, methods=30):
    (tmp_path / "app").mkdir()
    body = "".join(
        f"    def method_{i}(self):\n        value = {i}\n        return value\n\n"
        for i in range(methods)
    )
    (tmp_path / "app" / "big.py").write_text(
        "class Big:\n    def outer(self):\n        def inner():\n            return 1\n"
        "        return inner\n\n" + body
    )
    return tmp_path


def test_describe_symbol_outlines_a_class_whose_source_is_cut_off(tmp_path):
    details = describe_symbol(_big_class(tmp_path), "app.big.Big")

    assert details["source_truncated"] is True
    methods = details["outline"]["methods"].split(", ")
    assert methods[0] == "outer:2"
    assert [entry.split(":")[0] for entry in methods[1:]] == [
        f"method_{i}" for i in range(30)
    ]


def test_describe_symbol_outline_lists_only_direct_members(tmp_path):
    details = describe_symbol(_big_class(tmp_path), "app.big.Big")

    assert "inner" not in details["outline"]["methods"]


def test_describe_symbol_outline_groups_members_by_kind_on_one_line_each(tmp_path):
    (tmp_path / "app").mkdir()
    body = "".join(f"    def method_{i}(self):\n        return {i}\n" for i in range(40))
    (tmp_path / "app" / "big.py").write_text(
        "class Big:\n    first = 1\n    second = 2\n"
        + body
        + "    last = 3\n\n    class Meta:\n        ordering = 1\n"
    )

    details = describe_symbol(tmp_path, "app.big.Big")

    outline = details["outline"]
    assert outline["fields"] == "first, second, last"
    assert outline["methods"].startswith("method_0:4, method_1:6, ")
    assert outline["methods"].endswith("method_39:82")
    assert outline["classes"] == "Meta:86"


def test_describe_symbol_gives_no_outline_when_the_whole_class_is_shown(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.models.Widget")

    assert details["source_truncated"] is False
    assert "outline" not in details


def test_describe_symbol_gives_no_outline_for_a_long_function(tmp_path):
    (tmp_path / "app").mkdir()
    body = "".join(f"    x{i} = {i}\n" for i in range(300))
    (tmp_path / "app" / "long.py").write_text("def big():\n" + body)

    details = describe_symbol(tmp_path, "app.long.big")

    assert details["source_truncated"] is True
    assert "outline" not in details


def test_describe_symbol_lists_what_the_symbol_references(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(
        "LIMIT = 3\n\n\nclass Watch:\n    objects = None\n"
    )
    (tmp_path / "app" / "service.py").write_text(
        "from app.models import LIMIT, Watch\n\n\n"
        "def watches():\n    return Watch.objects, LIMIT\n\n\n"
        "def nothing():\n    return 1\n"
    )

    details = describe_symbol(tmp_path, "app.service.watches")

    assert {(ref["symbol"], ref["confidence"]) for ref in details["references"]} == {
        ("app.models.LIMIT", "high"),
        ("app.models.Watch", "high"),
        ("app.models.Watch.objects", "low"),
    }
    assert describe_symbol(tmp_path, "app.service.nothing")["references"] == []


def test_describe_symbol_suggests_the_closest_name_for_a_misspelling(tmp_path):
    (tmp_path / "cms").mkdir()
    (tmp_path / "cms" / "models.py").write_text(
        "class GiftCardWatchList:\n    pass\n\n\nclass Unrelated:\n    pass\n"
    )

    details = describe_symbol(tmp_path, "cms.models.GiftCardWatchLst")

    assert details["found"] is False
    assert details["suggestions"] == ["cms.models.GiftCardWatchList"]


def test_describe_symbol_offers_no_suggestion_for_a_name_nothing_resembles(tmp_path):
    details = describe_symbol(_project(tmp_path), "app.models.Zzzzzz")

    assert details == {"found": False, "symbol": None}


def test_describe_symbol_replaces_bytes_that_are_not_valid_utf8_keeping_line_numbers(
    tmp_path, monkeypatch
):
    (tmp_path / "legacy.py").write_bytes(b"x = 1\ndef f():\n    return 'caf\xe9'\n")
    context = {
        "found": True,
        "symbol": {
            "name": "f",
            "qualified_name": "legacy.f",
            "kind": "function",
            "start_line": 2,
            "end_line": 3,
            "file": "legacy.py",
        },
    }
    monkeypatch.setattr(
        "project_mcp.tools.symbol_details._resolve", lambda *a, **k: context
    )

    details = describe_symbol(tmp_path, "legacy.f")

    assert details["source"] == "def f():\n    return 'caf�'"
    assert "source_error" not in details
