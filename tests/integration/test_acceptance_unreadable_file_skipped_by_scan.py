from project_mcp.db import get_connection
from project_mcp.tools.project import get_project_overview


def test_a_scan_skips_an_unreadable_file_and_indexes_the_rest(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    locked = tmp_path / "locked.py"
    locked.write_text("def hidden():\n    pass\n")
    locked.chmod(0)

    overview = get_project_overview(tmp_path)

    paths = [path for (path,) in get_connection(tmp_path).execute("SELECT path FROM files")]
    assert overview["index_status"]["status"] == "fresh"
    assert "app.py" in paths
    assert "locked.py" not in paths
