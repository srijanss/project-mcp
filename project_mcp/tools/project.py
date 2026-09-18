from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, get_index_status

MANIFEST_NAMES = {
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
}


def get_project_overview(project_root: Path) -> dict:
    project_root = Path(project_root)
    config = load_config(project_root)
    conn = get_connection(project_root)

    ensure_fresh_index(conn, project_root, config)

    project_row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?", (str(project_root),)
    ).fetchone()
    project_id = project_row[0] if project_row else None

    rows = conn.execute(
        "SELECT path, language, file_kind FROM files WHERE project_id = ?",
        (project_id,),
    ).fetchall()

    languages = sorted({language for _, language, _ in rows if language})

    file_counts: dict = {}
    for _, _, file_kind in rows:
        file_counts[file_kind] = file_counts.get(file_kind, 0) + 1

    manifests = sorted(
        path for path, _, _ in rows if Path(path).name in MANIFEST_NAMES
    )

    source_roots = (
        list(config.source_roots)
        if config.source_roots
        else sorted(
            {
                Path(path).parts[0]
                for path, _, file_kind in rows
                if file_kind == "source" and len(Path(path).parts) > 1
            }
        )
    )
    test_roots = (
        list(config.test_roots)
        if config.test_roots
        else sorted(
            {
                Path(path).parts[0]
                for path, _, file_kind in rows
                if file_kind == "test" and len(Path(path).parts) > 1
            }
        )
    )

    return {
        "project": {"root_path": str(project_root)},
        "languages": languages,
        "source_roots": source_roots,
        "test_roots": test_roots,
        "manifests": manifests,
        "framework_hints": [],
        "file_counts": file_counts,
        "index_status": get_index_status(conn),
    }
