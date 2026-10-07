from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, get_index_status
from project_mcp.plugins.registry import PluginRegistry, configured_registry


def get_project_overview(
    project_root: Path, registry: PluginRegistry | None = None
) -> dict:
    project_root = Path(project_root)
    config = load_config(project_root)
    if registry is None:
        registry = configured_registry(config)
    conn = get_connection(project_root)

    ensure_fresh_index(conn, project_root, config, registry)

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

    manifest_names = {
        name
        for descriptor in registry.language_descriptors()
        for name in descriptor.manifests
    }
    manifests = sorted(
        path for path, _, _ in rows if Path(path).name in manifest_names
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
