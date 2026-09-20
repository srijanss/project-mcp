"""Contract tests for what Project MCP provides to TDD MCP (SPEC MVP 15)."""

from pathlib import Path

from project_mcp.tools.context_packs import (
    get_context_for_feature,
    get_context_for_symbol,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONTRACT_DOC = PROJECT_ROOT / "docs" / "tdd-mcp-contract.md"

TDD_CONTRACT_FIELDS = {
    "related_tests": list,
    "entrypoints": list,
    "dependencies": list,
    "recommended_files_to_open": list,
}


def _make_project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import VALUE\n\n\ndef test_value():\n    assert VALUE\n"
    )
    return tmp_path


class TestTddContextContract:
    def test_feature_context_exposes_stable_tdd_fields(self, tmp_path):
        context = get_context_for_feature(_make_project(tmp_path), "models")

        for field, expected_type in TDD_CONTRACT_FIELDS.items():
            assert field in context, f"missing contract field: {field}"
            assert isinstance(context[field], expected_type)

    def test_symbol_context_exposes_stable_tdd_fields(self, tmp_path):
        context = get_context_for_symbol(_make_project(tmp_path), "app.models")

        for field, expected_type in TDD_CONTRACT_FIELDS.items():
            assert field in context, f"missing contract field: {field}"
            assert isinstance(context[field], expected_type)


class TestTddContextEdgeCases:
    def test_feature_context_with_no_matches_keeps_contract_fields_empty(self, tmp_path):
        context = get_context_for_feature(_make_project(tmp_path), "zzz_nothing_matches")

        for field in TDD_CONTRACT_FIELDS:
            assert context[field] == []

    def test_feature_context_returns_structured_error_when_lookup_fails(
        self, tmp_path, monkeypatch
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("index unavailable")

        monkeypatch.setattr("project_mcp.tools.context_packs.find_symbol", boom)

        context = get_context_for_feature(_make_project(tmp_path), "models")

        assert context["type"] == "feature"
        assert context["status"] == "error"
        assert "index unavailable" in context["error"]


class TestTddContractDocumentation:
    def test_contract_doc_states_project_mcp_never_transitions_tdd_state(self):
        assert CONTRACT_DOC.exists()
        text = CONTRACT_DOC.read_text()

        assert "must not start or transition TDD state" in text
        for field in TDD_CONTRACT_FIELDS:
            assert field in text
