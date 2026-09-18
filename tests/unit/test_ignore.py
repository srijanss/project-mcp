from pathlib import Path

from project_mcp.config import ProjectConfig
from project_mcp.ignore import should_exclude


def _config(**overrides):
    return ProjectConfig(project_root=Path("/tmp/project"), **overrides)


def test_excludes_default_generated_dirs():
    config = _config()
    assert should_exclude(Path(".venv/lib/site-packages/foo.py"), config) is True
    assert should_exclude(Path("node_modules/pkg/index.js"), config) is True
    assert should_exclude(Path("target/debug/build.rs"), config) is True
    assert should_exclude(Path(".git/HEAD"), config) is True


def test_does_not_exclude_ordinary_source_file():
    config = _config()
    assert should_exclude(Path("app/models.py"), config) is False


def test_excludes_secret_like_files():
    config = _config()
    assert should_exclude(Path(".env"), config) is True
    assert should_exclude(Path("config/deploy_key.pem"), config) is True
    assert should_exclude(Path("id_rsa.key"), config) is True


def test_honors_config_exclude_overrides():
    config = _config(exclude=["scratch"])
    assert should_exclude(Path("scratch/notes.txt"), config) is True
    assert should_exclude(Path(".venv/foo.py"), config) is False
