from project_mcp.main_stdio import main


def test_a_plugins_value_that_is_not_a_table_is_a_clear_startup_error(tmp_path, capsys):
    (tmp_path / "mcpctl.toml").write_text("plugins = 5\n")

    exit_code = main([str(tmp_path)])

    assert exit_code == 1
    assert "invalid config: [plugins] must be a table, got 5" in capsys.readouterr().err
