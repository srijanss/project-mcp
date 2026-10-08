from pathlib import Path

from project_mcp.plugins.astro.framework import AstroFramework


def test_astro_pages_are_not_test_files_but_those_under_tests_are():
    framework = AstroFramework()

    assert not framework.is_test_file(Path("src/pages/index.astro"))
    assert framework.is_test_file(Path("tests/Card.astro"))


def test_astro_resolves_relative_imports_like_javascript_and_bare_packages_to_none():
    framework = AstroFramework()

    candidates = framework.resolve_import("src/pages/index.astro", "../components/Card")

    assert "src/components/Card.ts" in candidates
    assert framework.resolve_import("src/pages/index.astro", "astro") == []
