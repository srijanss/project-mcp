from types import SimpleNamespace

import pytest

from project_mcp.plugins.astro.framework import AstroFramework


def _detect(project_root):
    return AstroFramework().detect(SimpleNamespace(project_root=project_root))


def test_astro_framework_detects_astro_dependency_or_config(tmp_path):
    assert not _detect(tmp_path)

    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
    assert not _detect(tmp_path)

    (tmp_path / "package.json").write_text('{"devDependencies": {"astro": "^4.0.0"}}')
    assert _detect(tmp_path)


@pytest.mark.parametrize("name", ["astro.config.mjs", "astro.config.ts", "astro.config.js"])
def test_astro_framework_detects_an_astro_config_file(tmp_path, name):
    (tmp_path / name).write_text("export default {};\n")

    assert _detect(tmp_path)


def test_astro_framework_ignores_an_unreadable_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{not json")

    assert not _detect(tmp_path)
