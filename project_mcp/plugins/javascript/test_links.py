"""`tests` relationships from JS/TS test files to the project symbols they import."""
import json
from pathlib import Path

from project_mcp.plugins.react import exports, tree_usages, usages


def link_test_imports(context, analyzer) -> None:
    """Link each test file to the project symbols it statically imports.

    The link starts at the test file, since test callbacks are not indexed
    symbols. Every test file is relinked: reindexing an imported file
    replaces the symbols the links point at.
    """
    conn = context.conn
    for path in context.plugin_paths:
        if not analyzer.is_test_file(Path(path)):
            continue
        file_id = context.path_to_file_id[path]
        conn.execute(
            "DELETE FROM relationships WHERE source_entity_type = 'file'"
            " AND source_entity_id = ? AND relationship_type = 'tests'",
            (file_id,),
        )
        source = _source(context, path)
        if source is None:
            continue
        targets: list[int] = []
        for specifier, imported in _imported_names(analyzer, path, source).values():
            target = _imported_symbol(context, analyzer, path, specifier, imported)
            if target is not None and target not in targets:
                targets.append(target)
        for target in targets:
            conn.execute(
                """
                INSERT INTO relationships (
                    source_entity_type, source_entity_id,
                    target_entity_type, target_entity_id,
                    relationship_type, confidence, evidence_json
                ) VALUES ('file', ?, 'symbol', ?, 'tests', 'high', ?)
                """,
                (file_id, target, json.dumps(["direct_import"])),
            )


def _source(context, path: str) -> str | None:
    if path in context.changed:
        return context.changed[path].source
    try:
        return (Path(context.project_root) / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _imported_names(analyzer, path: str, source: str) -> dict[str, tuple[str, str]]:
    if analyzer.backend == "tree-sitter":
        return tree_usages.imported_names(source, tree_usages.grammar_for(path))
    return usages.imported_names(source)


def _imported_symbol(context, analyzer, importer: str, specifier: str, imported: str) -> int | None:
    """The symbol an import names: an export by its name, or the default export."""
    target_path = next(
        (c for c in analyzer.resolve_import(importer, specifier) if c in context.path_to_file_id),
        None,
    )
    if target_path is None:
        return None
    if imported == "default":
        source = _source(context, target_path)
        if source is None:
            return None
        if analyzer.backend == "tree-sitter":
            imported = tree_usages.default_export_name(source, tree_usages.grammar_for(target_path))
        else:
            imported = exports.default_export_name(source)
        if imported is None:
            return None
    row = context.conn.execute(
        "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
        (context.path_to_file_id[target_path], f"{analyzer.module_name(target_path)}.{imported}"),
    ).fetchone()
    return row[0] if row else None
