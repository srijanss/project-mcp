from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "app.py": "def target():\n    return 1\n",
    "tests/test_app.py": (
        "from unittest import mock\n"
        "from app import target\n\n"
        "@mock.patch('app.target')\n"
        "def test_target(m):\n    target()\n"
    ),
}


def test_a_test_that_becomes_unreadable_stays_set_aside_as_mocking_the_symbol(tmp_path, monkeypatch):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    before = get_tests_for(tmp_path, "app.target")
    assert [row.get("tests") for row in before] == [None]
    (tmp_path / "other.py").write_text("X = 1\n")
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == "test_app.py":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "app.target") == before
