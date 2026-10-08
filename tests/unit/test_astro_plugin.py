from types import SimpleNamespace

from project_mcp.plugins.registry import builtin_registry


def _astro(registry):
    (astro,) = [f for f in registry.frameworks() if type(f).__name__ == "AstroFramework"]
    return astro


def _detects(registry, project_root):
    return _astro(registry).detect(SimpleNamespace(project_root=project_root))


def test_astro_framework_plugin_detects_astro_projects(tmp_path):
    registry = builtin_registry()

    assert "astro" in registry.active_plugins()
    assert not _detects(registry, tmp_path)

    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}')
    assert _detects(registry, tmp_path)

    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
    assert not _detects(registry, tmp_path)

    (tmp_path / "astro.config.mjs").write_text("export default {};\n")
    assert _detects(registry, tmp_path)


def test_astro_framework_plugin_is_skipped_without_javascript():
    registry = builtin_registry()
    registry.disable("javascript")

    assert "astro" not in registry.active_plugins()
    assert registry.skipped_frameworks()["astro"] == ["javascript"]
