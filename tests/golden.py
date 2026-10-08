"""Golden snapshots of index output, compared during the plugin migration.

A snapshot names every row by path and qualified name rather than database
id, so it is the same whichever order rows were written in.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

_FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"
_SNAPSHOTS_ROOT = _FIXTURES_ROOT / "golden"

FIXTURES = {
    name: _FIXTURES_ROOT / name / "sample_project"
    for name in ("python", "javascript", "react", "rust")
}

_SYMBOL_COLUMNS = (
    "name",
    "qualified_name",
    "kind",
    "language",
    "start_line",
    "end_line",
    "visibility",
)
_DEPENDENCY_COLUMNS = (
    "name",
    "ecosystem",
    "declared_version",
    "resolved_version",
    "source_file",
    "scope",
)


def _json(value: str | None):
    return None if value is None else json.loads(value)


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def golden_config(project_root: Path):
    """The fixture's config with framework plugins off, so a snapshot is the generic model."""
    config = load_config(project_root)
    config.plugins_disabled = sorted({*config.plugins_disabled, "react"})
    return config


def copy_fixture(name: str, destination: Path) -> Path:
    project_root = destination / FIXTURES[name].name
    shutil.copytree(FIXTURES[name], project_root)
    return project_root


def load_snapshot(name: str) -> dict:
    return json.loads((_SNAPSHOTS_ROOT / f"{name}.json").read_text())


def touch_indexed_files(conn: sqlite3.Connection, project_root: Path) -> None:
    """Move every indexed file's mtime on, so refresh re-analyzes it."""
    for path, mtime_ns in conn.execute("SELECT path, mtime_ns FROM files"):
        later = mtime_ns + 1_000_000_000
        os.utime(project_root / path, ns=(later, later))


def write_snapshot(name: str) -> None:
    """Re-record a fixture's snapshot from the current scan output."""
    with tempfile.TemporaryDirectory() as tmp:
        project_root = copy_fixture(name, Path(tmp))
        conn = get_connection(project_root)
        run_scan(conn, project_root, golden_config(project_root))
        snapshot = dump_snapshot(conn)
        conn.close()
    (_SNAPSHOTS_ROOT / f"{name}.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    )


def dump_snapshot(conn: sqlite3.Connection) -> dict:
    file_paths = dict(conn.execute("SELECT id, path FROM files"))
    symbols = {
        row[0]: {"symbol": row[1], "path": file_paths[row[2]]}
        for row in conn.execute("SELECT id, qualified_name, file_id FROM symbols")
    }

    def entity(entity_type: str, entity_id: int) -> dict:
        if entity_type == "symbol":
            return symbols[entity_id]
        if entity_type == "file":
            return {"file": file_paths[entity_id]}
        raise ValueError(f"unexpected entity type {entity_type!r}")

    return {
        "files": _sorted(
            [
                {"path": path, "language": language, "file_kind": file_kind}
                for path, language, file_kind in conn.execute(
                    "SELECT path, language, file_kind FROM files"
                )
            ]
        ),
        "symbols": _sorted(
            [
                {
                    "path": file_paths[row[0]],
                    **dict(zip(_SYMBOL_COLUMNS, row[1:-1])),
                    "metadata": _json(row[-1]),
                }
                for row in conn.execute(
                    f"SELECT file_id, {', '.join(_SYMBOL_COLUMNS)}, metadata_json"
                    " FROM symbols"
                )
            ]
        ),
        "relationships": _sorted(
            [
                {
                    "source": entity(row[0], row[1]),
                    "target": entity(row[2], row[3]),
                    "relationship_type": row[4],
                    "confidence": row[5],
                    "evidence": _json(row[6]),
                }
                for row in conn.execute(
                    "SELECT source_entity_type, source_entity_id,"
                    " target_entity_type, target_entity_id, relationship_type,"
                    " confidence, evidence_json FROM relationships"
                )
            ]
        ),
        "tests": _sorted(
            [
                {
                    "path": file_paths[file_id],
                    "symbol": None if symbol_id is None else symbols[symbol_id]["symbol"],
                    "test_kind": test_kind,
                    "framework": framework,
                    "metadata": _json(metadata),
                }
                for symbol_id, file_id, test_kind, framework, metadata in conn.execute(
                    "SELECT symbol_id, file_id, test_kind, framework, metadata_json"
                    " FROM tests"
                )
            ]
        ),
        "dependencies": _sorted(
            [
                {**dict(zip(_DEPENDENCY_COLUMNS, row[:-1])), "metadata": _json(row[-1])}
                for row in conn.execute(
                    f"SELECT {', '.join(_DEPENDENCY_COLUMNS)}, metadata_json"
                    " FROM dependencies"
                )
            ]
        ),
    }


if __name__ == "__main__":
    for fixture_name in sys.argv[1:] or sorted(FIXTURES):
        write_snapshot(fixture_name)
