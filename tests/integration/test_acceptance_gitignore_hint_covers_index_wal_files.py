import fnmatch
import re
from pathlib import Path

import pytest

from project_mcp.db import get_connection

SPEC = Path(__file__).resolve().parents[2] / "SPEC.md"


def _recommended_gitignore_patterns() -> list[str]:
    match = re.search(r"Recommended `\.gitignore`:\s*```text\n(.*?)```", SPEC.read_text(), re.DOTALL)
    assert match, "SPEC.md has no recommended .gitignore block"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def _ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def test_the_recommended_gitignore_ignores_every_file_an_open_index_leaves_behind(tmp_path):
    """An open WAL index also writes index.db-wal and index.db-shm; none may show up in git status."""
    conn = get_connection(tmp_path)
    try:
        conn.execute("INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('index_status', 'fresh')")
        conn.commit()
        generated = sorted(f".project-mcp/{p.name}" for p in (tmp_path / ".project-mcp").iterdir())
    finally:
        conn.close()

    patterns = _recommended_gitignore_patterns()

    assert ".project-mcp/index.db-wal" in generated
    assert [path for path in generated if not _ignored(path, patterns)] == []
    assert not _ignored(".project-mcp/config.toml", patterns)


@pytest.mark.parametrize("sidecar", ["", "-wal", "-shm", "-journal"])
def test_the_recommended_gitignore_covers_every_sqlite_file_of_the_index(sidecar):
    """WAL mode writes -wal/-shm; an index left in rollback mode (busy upgrade) writes -journal."""
    assert _ignored(f".project-mcp/index.db{sidecar}", _recommended_gitignore_patterns())
