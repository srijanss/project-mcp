from project_mcp.tools.project import get_project_overview


def test_overview_lists_active_plugins_and_uncovered_languages_with_file_counts(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "a.rs").write_text("pub fn a() {}\n")
    (tmp_path / "b.rs").write_text("pub fn b() {}\n")
    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "README.md").write_text("# demo\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')

    overview = get_project_overview(tmp_path)

    assert overview["active_plugins"] == ["python", "javascript", "django"]
    assert overview["uncovered_languages"] == {"go": 1, "rust": 2}
