from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "a.py": "def f():\n    return 1\n",
    "b.py": "from a import f\n\n\ndef g():\n    return f()\n",
    "tests/test_a.py": "from a import f\n\n\ndef test_f():\n    assert f()\n",
}


def test_a_file_that_becomes_unreadable_before_relinking_does_not_abort_the_refresh(
    tmp_path, monkeypatch
):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    (tmp_path / "c.py").write_text("from a import f\n\n\ndef h():\n    return f()\n")
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name in {"b.py", "test_a.py"}:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    run_scan(conn, tmp_path, load_config(tmp_path))

    importers = {d["source"] for d in get_dependents(tmp_path, "a") if d["relationship_type"] == "imports"}
    assert {"b.py", "c.py"} <= importers
