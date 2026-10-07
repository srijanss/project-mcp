import errno

from project_mcp import indexer
from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan


def test_an_analysis_error_names_the_file_relative_to_the_project_root(
    tmp_path, monkeypatch
):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "gone.py").write_text("def hidden():\n    pass\n")

    def deny(path):
        raise PermissionError(errno.EACCES, "Permission denied", str(path))

    monkeypatch.setattr(indexer, "_read_source", deny)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    (error,) = conn.execute(
        "SELECT analysis_error FROM files WHERE path = 'pkg/gone.py'"
    ).fetchone()
    assert error == "PermissionError: [Errno 13] Permission denied: 'pkg/gone.py'"
