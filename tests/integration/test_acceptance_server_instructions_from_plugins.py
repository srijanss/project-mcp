from project_mcp.main_stdio import build_server


def test_server_instructions_name_the_analyzed_languages_and_ask_to_report_gaps(tmp_path):
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')

    instructions = build_server(tmp_path).instructions

    assert "Active plugins: python, javascript, django, astro, react." in instructions
    assert "Analyzed languages: astro, javascript, python, typescript." in instructions
    assert "rust" not in instructions
    assert "tell the user which files were not analyzed" in instructions
