import os

from project_mcp.db import get_connection
from project_mcp.tools.project import get_project_overview


def test_a_file_symlink_pointing_outside_the_project_is_never_indexed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "elsewhere.py").write_text("SECRET = 'not for the index'\n")
    (project / "app.py").write_text("def run():\n    pass\n")
    os.symlink(tmp_path / "elsewhere.py", project / "link.py")

    get_project_overview(project)

    conn = get_connection(project)
    assert [path for (path,) in conn.execute("SELECT path FROM files")] == ["app.py"]
    assert conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE name = 'SECRET'"
    ).fetchone()[0] == 0
