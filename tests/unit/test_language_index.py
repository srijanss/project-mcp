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


def test_write_file_analysis_stores_symbol_metadata_as_json(tmp_path):
    conn = get_connection(tmp_path)
    file_id = _file(conn, _project(conn, tmp_path), "shapes.toy")
    square = {**_symbol("Square", 1), "metadata": {"bases": ["Drawable"]}}

    write_file_analysis(
        conn, file_id, "toy", FileAnalysis(symbols=[square, _symbol("Drawable", 2)])
    )

    assert dict(conn.execute("SELECT qualified_name, metadata_json FROM symbols")) == {
        "shapes.Square": '{"bases": ["Drawable"]}',
        "shapes.Drawable": None,
    }


def test_link_imports_links_a_target_file_once(tmp_path):
    conn = get_connection(tmp_path)
    project_id = _project(conn, tmp_path)
    path_to_file_id = {
        path: _file(conn, project_id, path) for path in ["square.toy", "shapes.toy"]
    }

    link_imports(
        conn, "square.toy", ["shapes", "shapes"], _SameDirResolver(), path_to_file_id
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE relationship_type = 'imports'"
    ).fetchone()[0] == 1


def test_link_imports_retries_unresolved_imports_under_each_source_root(tmp_path):
    conn = get_connection(tmp_path)
    project_id = _project(conn, tmp_path)
    paths = ["main.toy", "colors.toy", "src/colors.toy", "src/shapes.toy", "lib/shapes.toy"]
    path_to_file_id = {path: _file(conn, project_id, path) for path in paths}

    link_imports(
        conn,
        "main.toy",
        ["colors", "shapes"],
        _SameDirResolver(),
        path_to_file_id,
        source_roots=["./src/", "lib"],
    )

    assert _imports(conn) == {
        (str({"file": "main.toy"}), str({"file": "colors.toy"})),
        (str({"file": "main.toy"}), str({"file": "src/shapes.toy"})),
    }


def test_write_file_analysis_never_looks_symbols_up(tmp_path):
    conn = get_connection(tmp_path)
    file_id = _file(conn, _project(conn, tmp_path), "shapes.toy")
    symbols = [_symbol(f"Shape{i}", i) for i in range(30)]
    edges = [(s["qualified_name"], "shapes.Shape0", "calls") for s in symbols[1:]]

    statements = []
    conn.set_trace_callback(statements.append)
    write_file_analysis(
        conn, file_id, "toy", FileAnalysis(symbols=symbols, symbol_edges=edges)
    )
    conn.set_trace_callback(None)

    assert [s for s in statements if s.lstrip().upper().startswith("SELECT")] == []
