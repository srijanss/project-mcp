from project_mcp import indexer
from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan


def test_a_source_that_cannot_be_read_at_analysis_fails_only_that_file(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "gone.py").write_text("def hidden():\n    pass\n")
    read_source = indexer._read_source

    def read_or_deny(path):
        if path.name == "gone.py":
            raise PermissionError(f"Permission denied: '{path}'")
        return read_source(path)

    monkeypatch.setattr(indexer, "_read_source", read_or_deny)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    status = {
        path: (state, (error or "").split(":")[0])
        for path, state, error in conn.execute(
            "SELECT path, analysis_status, analysis_error FROM files"
        )
    }
    assert status == {
        "app.py": ("analyzed", ""),
        "gone.py": ("file_failed", "PermissionError"),
    }
