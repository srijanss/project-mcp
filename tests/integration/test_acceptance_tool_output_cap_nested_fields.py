import asyncio
import json

from project_mcp.main_stdio import MAX_TOOL_OUTPUT_CHARS, build_server


def test_a_large_list_nested_in_a_dict_is_trimmed_to_fit_and_reported_by_its_path(tmp_path, monkeypatch):
    pack = {
        "target": "app.models",
        "metadata": {"owner": "app", "notes": [f"note {i} " + "x" * 200 for i in range(500)]},
    }
    monkeypatch.setattr("project_mcp.main_stdio.get_context_for_symbol", lambda *a, **k: pack)
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("get_context_for_symbol", {"qualified_name": "app.models"}))

    payload = json.loads(result.content[0].text)
    assert len(json.dumps(payload)) <= MAX_TOOL_OUTPUT_CHARS
    assert payload["truncated"] is True
    assert payload["truncated_fields"]["metadata.notes"]["total"] == 500
    assert payload["truncated_fields"]["metadata.notes"]["returned"] == len(payload["metadata"]["notes"])
    assert payload["metadata"]["owner"] == "app"
    assert payload["target"] == "app.models"
