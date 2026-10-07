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


def test_load_config_raises_clear_error_for_invalid_toml_syntax(tmp_path):
    project_mcp_dir = tmp_path / ".project-mcp"
    project_mcp_dir.mkdir()
    (project_mcp_dir / "config.toml").write_text("exclude = [oops")

    with pytest.raises(ConfigError, match="invalid config"):
        load_config(tmp_path)


def test_load_config_defaults_git_history_limit_to_100(tmp_path):
    config = load_config(tmp_path)

    assert config.git_history_limit == 100


def test_load_config_reads_git_history_limit_override_from_config_toml(tmp_path):
    project_mcp_dir = tmp_path / ".project-mcp"
    project_mcp_dir.mkdir()
    (project_mcp_dir / "config.toml").write_text("git_history_limit = 25\n")

    config = load_config(tmp_path)

    assert config.git_history_limit == 25


def test_load_config_defaults_legacy_thresholds(tmp_path):
    config = load_config(tmp_path)

    assert config.large_file_lines == 500
    assert config.large_symbol_lines == 100
    assert config.high_churn_count == 20
    assert config.high_fan_in_count == 15
    assert config.high_fan_out_count == 15
    assert config.high_temporal_coupling_count == 5


def test_load_config_reads_legacy_threshold_overrides_from_config_toml(tmp_path):
    project_mcp_dir = tmp_path / ".project-mcp"
    project_mcp_dir.mkdir()
    (project_mcp_dir / "config.toml").write_text(
        """
        large_file_lines = 300
        large_symbol_lines = 50
        high_churn_count = 10
        high_fan_in_count = 8
        high_fan_out_count = 8
        high_temporal_coupling_count = 3
        """
    )

    config = load_config(tmp_path)

    assert config.large_file_lines == 300
    assert config.large_symbol_lines == 50
    assert config.high_churn_count == 10
    assert config.high_fan_in_count == 8
    assert config.high_fan_out_count == 8
    assert config.high_temporal_coupling_count == 3


def test_load_config_raises_clear_error_for_negative_legacy_threshold(tmp_path):
    project_mcp_dir = tmp_path / ".project-mcp"
    project_mcp_dir.mkdir()
    (project_mcp_dir / "config.toml").write_text("large_file_lines = -1\n")

    with pytest.raises(ConfigError, match="large_file_lines"):
        load_config(tmp_path)


def test_load_config_raises_clear_error_for_non_integer_legacy_threshold(tmp_path):
    project_mcp_dir = tmp_path / ".project-mcp"
    project_mcp_dir.mkdir()
    (project_mcp_dir / "config.toml").write_text('high_churn_count = "many"\n')

    with pytest.raises(ConfigError, match="high_churn_count"):
        load_config(tmp_path)


def test_load_config_reads_max_file_bytes_and_defaults_it_to_one_mebibyte(tmp_path):
    assert load_config(tmp_path).max_file_bytes == 1024 * 1024

    (tmp_path / ".project-mcp" / "config.toml").write_text("max_file_bytes = 200\n")

    assert load_config(tmp_path).max_file_bytes == 200


def test_load_config_reads_plugin_selection_from_mcpctl_toml(tmp_path):
    (tmp_path / "mcpctl.toml").write_text(
        'name = "demo"\n\n[plugins]\nenabled = ["python"]\ndisabled = ["django"]\n'
    )

    config = load_config(tmp_path)

    assert (config.plugins_enabled, config.plugins_disabled) == (["python"], ["django"])


def test_load_config_enables_every_plugin_without_a_plugins_section(tmp_path):
    (tmp_path / "mcpctl.toml").write_text('name = "demo"\n')

    config = load_config(tmp_path)

    assert (config.plugins_enabled, config.plugins_disabled) == (None, [])
