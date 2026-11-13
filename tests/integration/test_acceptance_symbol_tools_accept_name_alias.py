import asyncio
import re

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from project_mcp.main_stdio import build_server

SPELLINGS = ["name", "query", "symbol", "qualified_name"]
SYMBOL_TOOLS = {
    "find_symbol": "Widget",
    "get_symbol_context": "app.models.Widget",
    "get_dependents": "app.models",
    "get_dependencies": "app.importer",
    "get_tests_for": "app.models",
    "get_context_for_symbol": "app.models.Widget",
}


@pytest.fixture
def server(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    (tmp_path / "app" / "importer.py").write_text("import app.models\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import Widget\n\n\ndef test_widget():\n    assert Widget()\n"
    )
    return build_server(tmp_path)


def _texts(result):
    assert result.is_error is False
    return [content.text for content in result.content]


@pytest.mark.parametrize("tool", SYMBOL_TOOLS)
def test_every_symbol_tool_answers_the_same_under_each_spelling(server, tool):
    target = SYMBOL_TOOLS[tool]

    answers = [_texts(asyncio.run(server.call_tool(tool, {spelling: target}))) for spelling in SPELLINGS]

    assert answers[0], "fixture should give every tool something to return"
    assert all(answer == answers[0] for answer in answers)


@pytest.mark.parametrize("tool", SYMBOL_TOOLS)
def test_a_missing_symbol_argument_names_all_four_spellings(server, tool):
    with pytest.raises(ToolError) as raised:
        asyncio.run(server.call_tool(tool, {}))

    for spelling in SPELLINGS:
        assert re.search(rf"\b{spelling}\b", str(raised.value))
