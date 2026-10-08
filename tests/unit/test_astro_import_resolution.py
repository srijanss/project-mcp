from project_mcp.plugins.astro.framework import AstroFramework

PAGE = "src/pages/index.astro"


def test_an_import_with_an_explicit_extension_names_exactly_that_file():
    framework = AstroFramework()

    assert framework.resolve_import(PAGE, "../layouts/Layout.astro") == ["src/layouts/Layout.astro"]
    assert framework.resolve_import(PAGE, "../data.js") == ["src/data.js"]


def test_an_extensionless_import_tries_astro_ts_and_js_files_and_index_files():
    candidates = AstroFramework().resolve_import(PAGE, "../components/Card")

    assert "src/components/Card.astro" in candidates
    assert "src/components/Card.ts" in candidates
    assert "src/components/Card/index.astro" in candidates


def test_bare_and_virtual_module_imports_resolve_to_none():
    framework = AstroFramework()

    assert framework.resolve_import(PAGE, "react") == []
    assert framework.resolve_import(PAGE, "astro:content") == []
