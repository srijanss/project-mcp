import asyncio
import json

from project_mcp.main_stdio import MAX_TOOL_OUTPUT_CHARS, build_server


def test_a_nested_dict_of_thousands_of_scalar_entries_is_trimmed_to_fit_and_reported(tmp_path, monkeypatch):
    pack = {
        "target": "app.models",
        "metrics": {f"symbol_{i}": i for i in range(5000)},
    }
    monkeypatch.setattr("project_mcp.main_stdio.get_context_for_symbol", lambda *a, **k: pack)
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("get_context_for_symbol", {"qualified_name": "app.models"}))

    payload = json.loads(result.content[0].text)
    assert len(result.content[0].text) <= MAX_TOOL_OUTPUT_CHARS
    assert payload["truncated"] is True
    assert payload["truncated_fields"]["metrics"]["total"] == 5000
    assert payload["truncated_fields"]["metrics"]["returned"] == len(payload["metrics"])
    assert payload["target"] == "app.models"
