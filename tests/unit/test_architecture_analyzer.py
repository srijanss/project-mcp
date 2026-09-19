"""Tests for detection of explicit architecture doc sources (MVP 10)."""

from pathlib import Path

from project_mcp.analyzers.generic.architecture import (
    detect_architecture_doc_sources,
    extract_architecture_facts,
)
from project_mcp.config import ProjectConfig


class TestDetectArchitectureDocSources:
    """Pure detection of which architecture doc sources exist in a project."""

    def test_detects_docs_architecture_directory(self, tmp_path):
        docs_dir = tmp_path / "docs" / "architecture"
        docs_dir.mkdir(parents=True)
        doc_file = docs_dir / "overview.md"
        doc_file.write_text("# Overview\n")

        sources = detect_architecture_doc_sources(tmp_path)

        paths = [s["path"] for s in sources]
        assert "docs/architecture/overview.md" in paths
        matching = next(s for s in sources if s["path"] == "docs/architecture/overview.md")
        assert matching["kind"] == "docs_architecture"

    def test_missing_docs_returns_empty_list(self, tmp_path):
        sources = detect_architecture_doc_sources(tmp_path)
        assert sources == []

    def test_detects_docs_adr_directory(self, tmp_path):
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        adr_file = adr_dir / "0001-use-sqlite.md"
        adr_file.write_text("# ADR 0001\n")

        sources = detect_architecture_doc_sources(tmp_path)

        matching = next(s for s in sources if s["path"] == "docs/adr/0001-use-sqlite.md")
        assert matching["kind"] == "docs_adr"

    def test_detects_root_level_adr_files(self, tmp_path):
        adr_file = tmp_path / "ADR-0002-something.md"
        adr_file.write_text("# ADR 0002\n")

        sources = detect_architecture_doc_sources(tmp_path)

        matching = next(s for s in sources if s["path"] == "ADR-0002-something.md")
        assert matching["kind"] == "adr_file"

    def test_detects_readme_architecture_section(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text(
            "# My Project\n\nSome intro.\n\n## Architecture\n\nDescribes the system.\n\n## Other\n\nMore stuff.\n"
        )

        sources = detect_architecture_doc_sources(tmp_path)

        matching = next(s for s in sources if s["path"] == "README.md")
        assert matching["kind"] == "readme_architecture_section"

    def test_readme_without_architecture_section_not_detected(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# My Project\n\nSome intro.\n\n## Installation\n\nSteps.\n")

        sources = detect_architecture_doc_sources(tmp_path)

        assert all(s["path"] != "README.md" for s in sources)

    def test_detects_configured_architecture_paths(self, tmp_path):
        doc_file = tmp_path / "docs" / "design.md"
        doc_file.parent.mkdir(parents=True)
        doc_file.write_text("# Design\n")
        config = ProjectConfig(project_root=tmp_path, architecture_docs=["docs/design.md"])

        sources = detect_architecture_doc_sources(tmp_path, config=config)

        matching = next(s for s in sources if s["path"] == "docs/design.md")
        assert matching["kind"] == "configured_path"


class TestExtractArchitectureFacts:
    """Simple heading-based fact extraction from detected doc sources (no LLM inference)."""

    def test_extracts_heading_facts_from_docs_architecture_file(self, tmp_path):
        docs_dir = tmp_path / "docs" / "architecture"
        docs_dir.mkdir(parents=True)
        doc_file = docs_dir / "payments.md"
        doc_file.write_text("# Payments\n\n## Depends on shared\n\nSome text.\n")
        sources = [{"path": "docs/architecture/payments.md", "kind": "docs_architecture"}]

        facts = extract_architecture_facts(tmp_path, sources)

        assert len(facts) == 2
        fact = next(f for f in facts if f["subject"] == "Depends on shared")
        assert fact["predicate"] == "documented_in"
        assert fact["object"] == "docs/architecture/payments.md"
        assert fact["origin"] == "explicit"
        assert fact["source"] == "docs/architecture/payments.md"

    def test_missing_sources_returns_empty_list(self, tmp_path):
        assert extract_architecture_facts(tmp_path, []) == []

    def test_extract_skips_non_utf8_doc_file_without_crashing(self, tmp_path):
        docs_dir = tmp_path / "docs" / "architecture"
        docs_dir.mkdir(parents=True)
        bad_file = docs_dir / "bad.md"
        bad_file.write_bytes(b"\xff\xfe# Not valid utf-8\n")
        good_file = docs_dir / "good.md"
        good_file.write_text("# Good\n\n## Depends on shared\n\nSome text.\n")
        sources = [
            {"path": "docs/architecture/bad.md", "kind": "docs_architecture"},
            {"path": "docs/architecture/good.md", "kind": "docs_architecture"},
        ]

        facts = extract_architecture_facts(tmp_path, sources)

        assert any(f["subject"] == "Depends on shared" for f in facts)
        assert all(f["source"] != "docs/architecture/bad.md" for f in facts)

    def test_doc_with_no_headings_produces_no_facts(self, tmp_path):
        docs_dir = tmp_path / "docs" / "architecture"
        docs_dir.mkdir(parents=True)
        (docs_dir / "empty.md").write_text("Just some prose, no headings here.\n")
        sources = [{"path": "docs/architecture/empty.md", "kind": "docs_architecture"}]

        facts = extract_architecture_facts(tmp_path, sources)

        assert facts == []

    def test_object_disambiguates_docs_with_same_filename_in_different_directories(self, tmp_path):
        (tmp_path / "docs" / "architecture").mkdir(parents=True)
        (tmp_path / "docs" / "architecture" / "design.md").write_text("# Architecture design\n")
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "design.md").write_text("# Legacy design\n")
        sources = [
            {"path": "docs/architecture/design.md", "kind": "docs_architecture"},
            {"path": "docs/design.md", "kind": "configured_path"},
        ]

        facts = extract_architecture_facts(tmp_path, sources)

        objects = {f["object"] for f in facts}
        assert len(objects) == 2
