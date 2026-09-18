import pytest

from project_mcp.config import ConfigError, load_config


def test_load_config_raises_clear_error_when_project_root_missing(tmp_path):
    missing_root = tmp_path / "does-not-exist"

    with pytest.raises(ConfigError, match="does not exist"):
        load_config(missing_root)


def test_load_config_creates_project_mcp_dir_when_missing(tmp_path):
    load_config(tmp_path)

    assert (tmp_path / ".project-mcp").is_dir()


def test_load_config_returns_default_excludes_when_no_config_toml(tmp_path):
    config = load_config(tmp_path)

    assert "node_modules" in config.exclude
    assert ".venv" in config.exclude
    assert "target" in config.exclude


def test_load_config_reads_overrides_from_config_toml(tmp_path):
    project_mcp_dir = tmp_path / ".project-mcp"
    project_mcp_dir.mkdir()
    (project_mcp_dir / "config.toml").write_text(
        """
        exclude = ["dist"]
        source_roots = ["src"]
        test_roots = ["tests"]
        architecture_docs = ["docs/architecture"]
        legacy_paths = ["legacy"]
        """
    )

    config = load_config(tmp_path)

    assert config.exclude == ["dist"]
    assert config.source_roots == ["src"]
    assert config.test_roots == ["tests"]
    assert config.architecture_docs == ["docs/architecture"]
    assert config.legacy_paths == ["legacy"]
