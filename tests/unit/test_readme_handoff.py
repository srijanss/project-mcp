from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[2] / "README.md"

REQUIRED_TOPICS = [
    "purpose",
    "project-agnostic",
    "rebuildable index",
    "setup",
    ".project-mcp/",
    "default excludes",
    "supported languages",
    "indexing lifecycle",
    "confidence",
    "evidence",
    "git history",
    "legacy signals",
    "explicit",
    "derived",
    "context pack",
    "benchmark",
    "add a new language analyzer",
    "add a framework analyzer",
    "TDD MCP",
    "Design Advisor MCP",
    "Architecture MCP",
    "Playwright MCP",
    "AKS MCP",
    "Deploy MCP",
]

REQUIRED_STATEMENT = (
    "Project MCP provides project facts. "
    "It does not make design or architecture decisions."
)

TOOL_NAMES = [
    "find_symbol",
    "get_architecture_context",
    "get_architecture_facts",
    "get_change_coupling",
    "get_change_history",
    "get_context_for_architecture",
    "get_context_for_bug",
    "get_context_for_feature",
    "get_context_for_refactor",
    "get_context_for_symbol",
    "get_dependencies",
    "get_dependency_version",
    "get_dependents",
    "get_hotspots",
    "get_index_status",
    "get_legacy_hotspots",
    "get_legacy_signals",
    "get_project_overview",
    "get_symbol_context",
    "get_test_summary",
    "get_tests_for",
    "list_dependencies",
    "refresh_index",
]


@pytest.fixture(scope="module")
def readme_text():
    assert README.is_file(), "README.md must exist at the project root"
    return README.read_text(encoding="utf-8")


def test_readme_exists_and_is_nonempty(readme_text):
    assert readme_text.strip()


@pytest.mark.parametrize("topic", REQUIRED_TOPICS)
def test_readme_covers_topic(readme_text, topic):
    assert topic.lower() in readme_text.lower()


def test_readme_states_facts_not_decisions(readme_text):
    assert REQUIRED_STATEMENT in readme_text


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_readme_documents_tool(readme_text, tool):
    assert tool in readme_text
