from project_mcp.db import get_connection
from project_mcp.tools.architecture import get_architecture_facts
from project_mcp.tools.project import get_project_overview
from tests.git_fixtures import build_git_fixture


def test_zero_active_plugins_index_files_at_file_level_with_a_warning(tmp_path):
    repo = build_git_fixture("churn-fixture", tmp_path)
    (repo / "mcpctl.toml").write_text("[plugins]\nenabled = []\n")
    (repo / "docs" / "architecture").mkdir(parents=True)
    (repo / "docs" / "architecture" / "core.md").write_text(
        "# core\n\n## core depends on storage\n"
    )

    overview = get_project_overview(repo)

    conn = get_connection(repo)
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert overview["index_status"]["status"] == "fresh"
    assert overview["index_status"].get("warnings") == [
        f"no language plugins active; indexed {file_count} files at file level only"
    ]
    assert "python" in overview["languages"]
    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert conn.execute(
        "SELECT g.change_count FROM git_facts g JOIN files f ON f.id = g.file_id"
        " WHERE f.path = 'file1.py'"
    ).fetchone()[0] == 4
    assert get_architecture_facts(repo) != []
