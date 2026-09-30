"""Tests for context packs — compact project context for AI clients."""

from pathlib import Path
import pytest

from project_mcp.tools.context_packs import (
    get_context_for_symbol,
    get_context_for_feature,
    get_context_for_bug,
    get_context_for_refactor,
    get_context_for_architecture,
)


class TestSymbolContext:
    """Get compact context for a specific symbol."""

    def test_get_context_for_symbol_basic(self):
        """Retrieve symbol definition and immediate dependents."""
        project_root = Path(__file__).parent.parent.parent

        # Get context for a known symbol
        context = get_context_for_symbol(project_root, "project_mcp.indexer.run_scan")

        assert context is not None
        assert "target" in context
        assert context["target"] == "project_mcp.indexer.run_scan"
        assert "type" in context
        assert context["type"] == "symbol"

    def test_symbol_context_includes_tests(self):
        """Include related test functions in symbol context."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_symbol(project_root, "project_mcp.indexer.run_scan")

        assert "related_tests" in context or "tests" in context or context.get("status") == "not_implemented"

    def test_symbol_context_related_tests_lists_covering_test_files(self, tmp_path):
        """related_tests should list actual test files covering the symbol, not always []."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_models.py").write_text(
            "from app.models import VALUE\n\n\ndef test_value():\n    assert VALUE\n"
        )

        context = get_context_for_symbol(tmp_path, "app.models")

        test_files = [t["test_file"] for t in context["related_tests"]]
        assert "tests/test_models.py" in test_files

    def test_symbol_context_is_compact(self):
        """Return only essential info, not entire files."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_symbol(project_root, "project_mcp.indexer.run_scan")

        # Should be a dict, not full source code
        assert isinstance(context, dict)
        # Should not include raw source
        context_str = str(context)
        assert len(context_str) < 5000  # Much smaller than actual source files

    def test_symbol_context_handles_nonexistent_symbol(self):
        """Return not_found status for symbols that don't exist."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_symbol(project_root, "nonexistent.module.symbol")

        assert context["type"] == "symbol"
        assert context["status"] == "not_found"
        assert "target" in context

    def test_symbol_context_handles_invalid_input(self):
        """Validate inputs and provide clear error messages."""
        project_root = Path(__file__).parent.parent.parent

        # Empty qualified name should not crash, but handle gracefully
        context = get_context_for_symbol(project_root, "")

        assert isinstance(context, dict)
        assert "type" in context
        assert context["type"] == "symbol"

    def test_symbol_context_truncation_has_indicator(self):
        """Truncated results include metadata about truncation."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_symbol(project_root, "project_mcp.indexer.run_scan")

        assert context["type"] == "symbol"
        # Response should indicate if results are truncated
        assert "imports" in context
        assert "used_by" in context
        # When we return limited results (10 items), should indicate total count
        assert "imports_total" in context or "used_by_total" in context or context.get("is_truncated") is not None

    def test_symbol_context_return_structure_consistent(self):
        """Success and not_found cases have consistent structure."""
        project_root = Path(__file__).parent.parent.parent

        success_context = get_context_for_symbol(project_root, "project_mcp.indexer.run_scan")
        notfound_context = get_context_for_symbol(project_root, "nonexistent.symbol")

        # Both should have these base keys
        assert "target" in success_context
        assert "type" in success_context
        assert "target" in notfound_context
        assert "type" in notfound_context

        # Success case should have additional keys
        assert "symbol" in success_context or "status" in success_context


class TestFeatureContext:
    """Discover context for a feature by query."""

    def test_feature_context_finds_related_symbols(self):
        """Find symbols related to a feature query."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_feature(project_root, "indexer")

        assert context is not None
        assert "type" in context
        assert context["type"] == "feature"
        assert "related_symbols" in context or context.get("status") == "not_implemented"

    def test_feature_query_matches_tests(self, tmp_path):
        """Locate tests related to feature query."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_widget.py").write_text(
            "def test_widget_creation():\n    assert True\n"
        )

        context = get_context_for_feature(tmp_path, "widget")

        assert any("test_widget" in t for t in context["related_tests"])

    def test_feature_context_includes_dependencies(self, tmp_path):
        """Include imported modules and dependencies."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
        (tmp_path / "app" / "widget.py").write_text("import app.models\n")

        context = get_context_for_feature(tmp_path, "widget")

        assert "dependencies" in context
        assert any("models" in dep["target"] for dep in context["dependencies"])


class TestBugContext:
    """Discover context for bug investigation."""

    def test_bug_context_finds_related_code(self):
        """Find code symbols related to bug query."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_bug(project_root, "indexing error")

        assert context is not None
        assert context["type"] == "bug"
        assert "related_symbols" in context or context.get("status") == "not_implemented"

    def test_bug_context_includes_callers(self, tmp_path):
        """Show functions that call the buggy code."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "workflow.py").write_text(
            "def broken():\n    return 1 / 0\n\n\ndef run():\n    return broken()\n"
        )

        context = get_context_for_bug(tmp_path, "broken")

        assert "callers" in context
        assert any("run" in c["source"] for c in context["callers"])

    def test_bug_context_includes_churn(self, tmp_path):
        """Flag high-churn files as higher risk."""
        import subprocess

        repo = tmp_path
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "app").mkdir()
        module = repo / "app" / "flaky.py"
        for i in range(5):
            module.write_text(f"def flaky():\n    return {i}\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"change {i}"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

        context = get_context_for_bug(repo, "flaky")

        assert "churn" in context
        flaky_entry = next((c for c in context["churn"] if c["path"] == "app/flaky.py"), None)
        assert flaky_entry is not None
        assert flaky_entry["change_count"] >= 5
        assert flaky_entry["high_risk"] is True


class TestRefactorContext:
    """Discover refactor impact and related code."""

    def test_refactor_context_shows_dependents(self):
        """Show all code using the target symbol."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_refactor(project_root, "project_mcp.indexer.run_scan")

        assert context is not None
        assert context["type"] == "refactor"
        assert "dependents" in context or context.get("status") == "not_implemented"

    def test_refactor_context_includes_tests(self, tmp_path):
        """Include tests for the refactored code."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_models.py").write_text(
            "from app.models import VALUE\n\n\ndef test_value():\n    assert VALUE\n"
        )

        context = get_context_for_refactor(tmp_path, "app.models")

        test_files = [t["test_file"] for t in context["related_tests"]]
        assert "tests/test_models.py" in test_files

    def test_refactor_context_includes_temporal_coupling(self, tmp_path):
        """Flag files changed together (co-change patterns)."""
        import subprocess

        repo = tmp_path
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "app").mkdir()
        a = repo / "app" / "a.py"
        b = repo / "app" / "b.py"
        for i in range(3):
            a.write_text(f"A = {i}\n")
            b.write_text(f"B = {i}\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"change {i}"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

        context = get_context_for_refactor(repo, "app.a")

        coupled_files = [c["file"] for c in context["temporal_coupling"]]
        assert "app/b.py" in coupled_files

    def test_refactor_context_includes_legacy_signals(self, tmp_path):
        """Surface evidence-backed legacy signals (e.g. large_file) for the target."""
        (tmp_path / "app").mkdir()
        a = tmp_path / "app" / "a.py"
        a.write_text("\n".join(f"A{i} = {i}" for i in range(501)) + "\n")

        context = get_context_for_refactor(tmp_path, "app.a")

        assert "legacy_signals" in context
        signals = [s["signal"] for s in context["legacy_signals"]]
        assert "large_file" in signals

    def test_refactor_context_legacy_signals_empty_when_none(self, tmp_path):
        """No legacy evidence should mean an empty list, not a fabricated signal."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "clean.py").write_text("VALUE = 1\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_clean.py").write_text(
            "from app.clean import VALUE\n\n\ndef test_value():\n    assert VALUE == 1\n"
        )

        context = get_context_for_refactor(tmp_path, "app.clean")

        assert context["legacy_signals"] == []


class TestArchitectureContext:
    """Get architecture-relevant context."""

    def test_architecture_context_returns_structure(self):
        """Include architecture-relevant context about an area."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_architecture(project_root, "indexer")

        assert context is not None
        assert context["type"] == "architecture"
        assert "structure" in context or context.get("status") == "not_implemented"

    def test_architecture_context_includes_inferred_structure(self, tmp_path):
        """Include dependency structure and patterns."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
        (tmp_path / "app" / "views.py").write_text("import app.models\n")

        context = get_context_for_architecture(tmp_path, "views")

        inferred = context["structure"]["inferred_structure"]
        assert any("models" in dep for module in inferred for dep in module["depends_on"])

    def test_architecture_context_distinguishes_sources(self, tmp_path):
        """Mark whether facts are explicit or inferred."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "views.py").write_text("VALUE = 1\n")
        (tmp_path / "docs" / "architecture").mkdir(parents=True)
        (tmp_path / "docs" / "architecture" / "views.md").write_text(
            "# views\n\n## views depends on models\n\nSome text.\n"
        )

        context = get_context_for_architecture(tmp_path, "views")

        explicit = context["structure"]["explicit_facts"]
        assert len(explicit) >= 1
        assert explicit[0]["origin"] == "explicit"

    def test_architecture_context_area_with_underscore_does_not_act_as_wildcard(self, tmp_path):
        """A literal underscore in `area` must not match arbitrary characters like a SQL LIKE '_' wildcard."""
        (tmp_path / "docs" / "architecture").mkdir(parents=True)
        (tmp_path / "docs" / "architecture" / "payments.md").write_text(
            "# payment_methods\n\n## paymentXmethods\n\nSome text.\n"
        )

        context = get_context_for_architecture(tmp_path, "payment_methods")

        subjects = [fact["subject"] for fact in context["structure"]["explicit_facts"]]
        assert "payment_methods" in subjects
        assert "paymentXmethods" not in subjects


class TestOtherContextsHandleNonexistentProjectRoot:
    """Error handling for a nonexistent project_root, matching get_context_for_symbol."""

    def test_feature_context_handles_nonexistent_project_root(self):
        context = get_context_for_feature(Path("/nonexistent/path"), "indexer")

        assert context["type"] == "feature"
        assert context.get("status") in ("error", "invalid_input")
        assert "error" in context

    def test_bug_context_handles_nonexistent_project_root(self):
        context = get_context_for_bug(Path("/nonexistent/path"), "indexer")

        assert context["type"] == "bug"
        assert context.get("status") in ("error", "invalid_input")
        assert "error" in context

    def test_refactor_context_handles_nonexistent_project_root(self):
        context = get_context_for_refactor(Path("/nonexistent/path"), "project_mcp.indexer.run_scan")

        assert context["type"] == "refactor"
        assert context.get("status") in ("error", "invalid_input")
        assert "error" in context

    def test_architecture_context_handles_nonexistent_project_root(self):
        context = get_context_for_architecture(Path("/nonexistent/path"), "indexer")

        assert context["type"] == "architecture"
        assert context.get("status") in ("error", "invalid_input")
        assert "error" in context


class TestSymbolContextErrorCases:
    """Error handling and edge cases for symbol context."""

    def test_symbol_context_handles_nonexistent_project_root(self):
        """Return error when project root doesn't exist."""
        context = get_context_for_symbol(Path("/nonexistent/path"), "project_mcp.indexer.run_scan")

        assert context["type"] == "symbol"
        assert context.get("status") in ("error", "invalid_input")
        assert "error" in context

    def test_symbol_context_edge_case_zero_dependents(self, tmp_path):
        """Handle symbols with no dependents gracefully.

        Uses an isolated fixture: asserting against project-mcp's own live
        dependency graph drifted whenever a new caller of the target symbol
        appeared (MVP 13's ensure_fresh_index(), then cross-module call
        indexing, which made run_scan grow to dozens of dependents).
        """
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "lonely.py").write_text("def lonely():\n    return 1\n")

        context = get_context_for_symbol(tmp_path, "app.lonely.lonely")

        assert context["type"] == "symbol"
        assert context["used_by_total"] == 0
        assert context.get("is_truncated_dependents") is False

    def test_symbol_context_truncation_metadata_accuracy(self):
        """Truncation metadata accurately reflects actual data."""
        project_root = Path(__file__).parent.parent.parent

        context = get_context_for_symbol(project_root, "project_mcp.indexer.run_scan")

        # Truncation flags should match the actual data
        if context["imports_total"] <= 10:
            assert context["is_truncated_imports"] is False
            assert len(context["imports"]) == context["imports_total"]
        else:
            assert context["is_truncated_imports"] is True
            assert len(context["imports"]) == 10

        # Same for dependents
        if context["used_by_total"] <= 10:
            assert context["is_truncated_dependents"] is False
        else:
            assert context["is_truncated_dependents"] is True
            assert len(context["used_by"]) == 10


class TestContextPackFormat:
    """Validate context pack structure and formatting."""

    def _all_packs(self, tmp_path):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "widget.py").write_text("def widget():\n    pass\n")

        return [
            get_context_for_symbol(tmp_path, "app.widget"),
            get_context_for_feature(tmp_path, "widget"),
            get_context_for_bug(tmp_path, "widget"),
            get_context_for_refactor(tmp_path, "app.widget"),
            get_context_for_architecture(tmp_path, "widget"),
        ]

    def test_context_pack_has_summary(self, tmp_path):
        """Every context pack includes a human-readable summary."""
        for context in self._all_packs(tmp_path):
            assert isinstance(context.get("summary"), str)
            assert len(context["summary"]) > 0

    def test_context_pack_has_recommended_files(self, tmp_path):
        """Include a list of files worth opening first."""
        for context in self._all_packs(tmp_path):
            assert "recommended_files_to_open" in context
            assert isinstance(context["recommended_files_to_open"], list)
            assert "app/widget.py" in context["recommended_files_to_open"]

    def test_context_pack_is_compact(self, tmp_path):
        """Verify result is substantially smaller than reading all files."""
        for context in self._all_packs(tmp_path):
            assert len(str(context)) < 5000


def _order_project_with_tests(root: Path) -> Path:
    (root / "app").mkdir()
    (root / "app" / "models.py").write_text(
        "class Order:\n    def refund(self):\n        return 1\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_orders.py").write_text(
        "from app.models import Order\n\n\n"
        "def test_refund():\n    order = Order()\n    assert order.refund()\n"
    )
    return root


def test_symbol_and_refactor_packs_list_related_test_files_without_naming_each_test(
    tmp_path,
):
    project_root = _order_project_with_tests(tmp_path)
    expected = [
        {
            "test_file": "tests/test_orders.py",
            "confidence": "high",
            "evidence": ["symbol_reference"],
        }
    ]

    symbol_pack = get_context_for_symbol(project_root, "app.models.Order.refund")
    refactor_pack = get_context_for_refactor(project_root, "app.models.Order.refund")

    assert symbol_pack["related_tests"] == expected
    assert refactor_pack["related_tests"] == expected
