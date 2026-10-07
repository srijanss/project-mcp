"""Writes language plugins' analyses into the index, whatever the language."""

import sqlite3

from project_mcp.plugins.analysis import FileAnalysis


def clear_file_symbols(conn: sqlite3.Connection, file_id: int) -> None:
    """Delete a file's symbols and every symbol edge touching them."""
    conn.execute(
        """
        DELETE FROM relationships
        WHERE (source_entity_type = 'symbol' AND source_entity_id IN
               (SELECT id FROM symbols WHERE file_id = ?))
           OR (target_entity_type = 'symbol' AND target_entity_id IN
               (SELECT id FROM symbols WHERE file_id = ?))
        """,
        (file_id, file_id),
    )
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))


def write_file_analysis(
    conn: sqlite3.Connection, file_id: int, language: str, analysis: FileAnalysis
) -> None:
    """Replace a file's symbols and same-file symbol edges with `analysis`."""
    clear_file_symbols(conn, file_id)
    symbol_ids: dict[str, int] = {}
    for symbol in analysis.symbols:
        cursor = conn.execute(
            """
            INSERT INTO symbols (
                file_id, name, qualified_name, kind, language,
                start_line, end_line, visibility
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                symbol["name"],
                symbol["qualified_name"],
                symbol["kind"],
                language,
                symbol["start_line"],
                symbol["end_line"],
                symbol["visibility"],
            ),
        )
        symbol_ids.setdefault(symbol["qualified_name"], cursor.lastrowid)

    for source, target, relationship_type in analysis.symbol_edges:
        if source not in symbol_ids or target not in symbol_ids:
            continue
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, ?, 'high')
            """,
            (symbol_ids[source], symbol_ids[target], relationship_type),
        )


def link_imports(
    conn: sqlite3.Connection,
    path: str,
    imports: list[str],
    analyzer,
    path_to_file_id: dict[str, int],
) -> None:
    """Replace `path`'s file import edges, resolving each import via `analyzer`.

    An import links to the first candidate path that is an indexed file;
    imports that resolve to nothing, or to the importing file, are dropped.
    """
    file_id = path_to_file_id[path]
    conn.execute(
        """
        DELETE FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND relationship_type = 'imports'
        """,
        (file_id,),
    )
    for module in imports:
        target_file_id = next(
            (
                path_to_file_id[candidate]
                for candidate in analyzer.resolve_import(path, module)
                if candidate in path_to_file_id
            ),
            None,
        )
        if target_file_id is None or target_file_id == file_id:
            continue
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('file', ?, 'file', ?, 'imports', 'high')
            """,
            (file_id, target_file_id),
        )
