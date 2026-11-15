import fnmatch
import re
import tomllib
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


MCPCTL = Path(__file__).resolve().parents[2] / "mcpctl.toml"


def _gitignore_hint_patterns() -> list[str]:
    hints = [h["message"] for h in tomllib.loads(MCPCTL.read_text())["scaffold"]["hints"]]
    gitignore_hints = [m for m in hints if ".gitignore" in m]
    assert len(gitignore_hints) == 1, gitignore_hints
    return re.findall(r"\.project-mcp/[\w.*-]+", gitignore_hints[0])


@pytest.mark.parametrize("generated", ["index.db", "index.db-wal", "index.db-shm", "state.json"])
def test_the_scaffold_gitignore_hint_covers_the_index_and_its_wal_files(generated):
    """Following mcpctl's printed hint word for word must leave no WAL file untracked."""
    patterns = _gitignore_hint_patterns()

    assert _ignored(f".project-mcp/{generated}", patterns)
    assert not _ignored(".project-mcp/config.toml", patterns)


README = Path(__file__).resolve().parents[2] / "README.md"


def _readme_section(heading: str) -> str:
    """The README text under `heading` up to the next heading, whitespace-collapsed."""
    body = README.read_text().split(heading, 1)[1].split("\n#", 1)[0]
    return " ".join(body.split())


@pytest.mark.parametrize("sidecar", ["index.db-wal", "index.db-shm"])
def test_the_readme_describes_the_wal_files_as_part_of_the_disposable_index(sidecar):
    """README's .project-mcp/ list and its "safe to delete" note both name the WAL files."""
    state_list = _readme_section("## Project-local `.project-mcp/`")
    rebuildable = _readme_section("## SQLite as a rebuildable index")

    assert sidecar in state_list
    assert sidecar in rebuildable


def test_the_readme_only_allows_deleting_the_index_once_no_server_has_it_open():
    """Deleting live WAL/SHM files under an open connection can corrupt the index."""
    rebuildable = _readme_section("## SQLite as a rebuildable index")

    assert "at any time" not in rebuildable
    assert "stop every project-mcp server" in rebuildable


def test_the_readme_says_to_delete_the_index_and_its_wal_files_together():
    """A stale -wal/-shm left beside a fresh index.db must not be paired with it."""
    rebuildable = _readme_section("## SQLite as a rebuildable index")

    assert "delete `.project-mcp/index.db*`" in rebuildable
