from project_mcp.main_stdio import main


def test_an_unknown_plugin_in_plugins_enabled_is_a_clear_startup_error(tmp_path, capsys):
    (tmp_path / "mcpctl.toml").write_text('[plugins]\nenabled = ["pyhton"]\n')

    exit_code = main([str(tmp_path)])

    assert exit_code == 1
    assert (
        "unknown plugin pyhton in mcpctl.toml plugins.enabled"
        " (installed: python, javascript, rust, django, astro, react)"
    ) in capsys.readouterr().err
