from project_mcp.db import get_connection
from project_mcp.language_index import link_imports, write_file_analysis
from project_mcp.plugins.analysis import FileAnalysis
from tests.golden import dump_snapshot


def _file(conn, project_id, path):
    return conn.execute(
        "INSERT INTO files (project_id, path) VALUES (?, ?)", (project_id, path)
    ).lastrowid


def _project(conn, root):
    return conn.execute(
        "INSERT INTO projects (root_path, created_at) VALUES (?, '2026-01-01')",
        (str(root),),
    ).lastrowid


def _symbol(name, line):
    return {
        "name": name,
        "qualified_name": f"shapes.{name}",
        "kind": "class",
        "start_line": line,
        "end_line": line,
        "visibility": "public",
    }


def test_write_file_analysis_stores_symbols_and_same_file_edges(tmp_path):
    conn = get_connection(tmp_path)
    file_id = _file(conn, _project(conn, tmp_path), "shapes.toy")
    analysis = FileAnalysis(
        symbols=[_symbol("Square", 1), _symbol("Drawable", 2)],
        symbol_edges=[("shapes.Square", "shapes.Drawable", "implements")],
    )

    write_file_analysis(conn, file_id, "toy", analysis)

    snapshot = dump_snapshot(conn)
    assert {(s["qualified_name"], s["language"]) for s in snapshot["symbols"]} == {
        ("shapes.Drawable", "toy"),
        ("shapes.Square", "toy"),
    }
    assert snapshot["relationships"] == [
        {
            "source": {"symbol": "shapes.Square", "path": "shapes.toy"},
            "target": {"symbol": "shapes.Drawable", "path": "shapes.toy"},
            "relationship_type": "implements",
            "confidence": "high",
            "evidence": None,
        }
    ]


class _SameDirResolver:
    def resolve_import(self, importer: str, module: str) -> list[str]:
        return [f"{module}.toy", f"{module}/index.toy"]


def _imports(conn):
    return {
        (str(row["source"]), str(row["target"]))
        for row in dump_snapshot(conn)["relationships"]
        if row["relationship_type"] == "imports"
    }


def test_link_imports_replaces_a_files_imports_with_resolvable_targets(tmp_path):
    conn = get_connection(tmp_path)
    project_id = _project(conn, tmp_path)
    paths = ["square.toy", "shapes.toy", "colors/index.toy"]
    path_to_file_id = {path: _file(conn, project_id, path) for path in paths}
    resolver = _SameDirResolver()

    link_imports(
        conn, "square.toy", ["shapes", "missing"], resolver, path_to_file_id
    )
    link_imports(
        conn, "square.toy", ["colors", "square"], resolver, path_to_file_id
    )

    assert _imports(conn) == {
        (str({"file": "square.toy"}), str({"file": "colors/index.toy"}))
    }
