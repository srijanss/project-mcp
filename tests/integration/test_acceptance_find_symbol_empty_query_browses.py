import asyncio
import json

import pytest

from project_mcp.main_stdio import build_server


@pytest.fixture
def server(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(
        "class Widget:\n    pass\n\n\nclass Gadget:\n    pass\n\n\ndef build():\n    pass\n"
    )
    return build_server(tmp_path)


@pytest.mark.parametrize("spelling", ["query", "name", "symbol", "qualified_name"])
def test_an_empty_find_symbol_query_browses_symbols_of_a_kind(server, spelling):
    result = asyncio.run(server.call_tool("find_symbol", {spelling: "", "kind": "class", "limit": 1}))

    assert result.is_error is False
    page = json.loads(result.content[0].text)
    assert page["truncated"] is True
    assert [item["name"] for item in page["items"]] in (["Gadget"], ["Widget"])
    assert page["next_offset"] == 1
