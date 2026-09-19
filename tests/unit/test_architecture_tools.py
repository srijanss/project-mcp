"""Tests for the spec-named architecture MCP tool wrappers."""

from pathlib import Path

from project_mcp.tools.architecture import get_architecture_context, get_architecture_facts
from project_mcp.tools.context_packs import get_context_for_architecture


def test_get_architecture_facts_returns_indexed_explicit_facts(tmp_path):
    (tmp_path / "docs" / "architecture").mkdir(parents=True)
    (tmp_path / "docs" / "architecture" / "payments.md").write_text(
        "# Payments\n\n## Depends on shared\n\nSome text.\n"
    )

    facts = get_architecture_facts(tmp_path)

    assert isinstance(facts, list)
    fact = next(f for f in facts if f["subject"] == "Depends on shared")
    assert fact["predicate"] == "documented_in"
    assert fact["object"] == "docs/architecture/payments.md"
    assert fact["origin"] == "explicit"
    assert fact["source"] == "docs/architecture/payments.md"


def test_get_architecture_facts_missing_docs_returns_empty_list(tmp_path):
    facts = get_architecture_facts(tmp_path)

    assert facts == []


def test_get_architecture_context_with_no_area_returns_all_facts(tmp_path):
    (tmp_path / "docs" / "architecture").mkdir(parents=True)
    (tmp_path / "docs" / "architecture" / "payments.md").write_text(
        "# Payments\n\n## Depends on shared\n\nSome text.\n"
    )

    context = get_architecture_context(tmp_path)

    assert len(context["facts"]) == 2


def test_get_architecture_context_filters_facts_by_area(tmp_path):
    (tmp_path / "docs" / "architecture").mkdir(parents=True)
    (tmp_path / "docs" / "architecture" / "payments.md").write_text(
        "# Payments\n\n## Depends on shared\n\nSome text.\n"
    )
    (tmp_path / "docs" / "architecture" / "orders.md").write_text(
        "# Orders\n\n## Depends on shared\n\nSome text.\n"
    )

    context = get_architecture_context(tmp_path, area="payments")

    assert len(context["facts"]) >= 1
    assert all(
        "payments" in fact["subject"].lower() or "payments" in fact["object"].lower()
        for fact in context["facts"]
    )


def test_real_adr_file_produces_indexed_facts_reflected_in_architecture_context(tmp_path):
    """End-to-end: a real ADR file on disk drives both get_architecture_facts and
    get_context_for_architecture's explicit_facts, distinguishable from inferred structure."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "payments.py").write_text("import app.shared\n")
    (tmp_path / "app" / "shared.py").write_text("VALUE = 1\n")
    (tmp_path / "ADR-0001-payments-depends-on-shared.md").write_text(
        "# ADR 0001\n\n## payments may depend on shared\n\nRationale.\n"
    )

    facts = get_architecture_facts(tmp_path)
    assert any(f["subject"] == "payments may depend on shared" for f in facts)
    assert all(f["origin"] == "explicit" for f in facts)

    context = get_context_for_architecture(tmp_path, "payments")

    explicit = context["structure"]["explicit_facts"]
    assert any(f["subject"] == "payments may depend on shared" for f in explicit)
    assert all(f["origin"] == "explicit" for f in explicit)
    assert all(f["source"] == "ADR-0001-payments-depends-on-shared.md" for f in explicit)
