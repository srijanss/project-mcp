from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.analysis import ChangedFile, LinkContext
from project_mcp.plugins.python.analyzer import PythonAnalyzer
from project_mcp.plugins.python.descriptor import DESCRIPTOR
from project_mcp.plugins.registry import PluginRegistry


class _PythonWithoutLinking(PythonAnalyzer):
    link_cross_file = None
    link_test_evidence = None


def _scan_without_linking(project_root, files):
    for path, source in files.items():
        (project_root / path).parent.mkdir(parents=True, exist_ok=True)
        (project_root / path).write_text(source)
    registry = PluginRegistry()
    registry.register(replace(DESCRIPTOR, analyzer=f"{__name__}:_PythonWithoutLinking"))
    conn = get_connection(project_root)
    run_scan(conn, project_root, load_config(project_root), registry=registry)
    return conn


def _context(conn, project_root, files):
    path_to_file_id = dict(conn.execute("SELECT path, id FROM files"))
    analyzer = PythonAnalyzer()
    return LinkContext(
        conn=conn,
        project_root=project_root,
        source_roots=[],
        path_to_file_id=path_to_file_id,
        changed={
            path: ChangedFile(path_to_file_id[path], source, analyzer.analyze(path, source))
            for path, source in files.items()
        },
        added=set(files),
        plugin_paths=list(files),
    )


def _edges(conn, relationship_type):
    return set(
        conn.execute(
            """
            SELECT source.qualified_name, target.qualified_name FROM relationships r
            JOIN symbols source ON source.id = r.source_entity_id
            JOIN symbols target ON target.id = r.target_entity_id
            WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
              AND r.relationship_type = ?
            """,
            (relationship_type,),
        )
    )


FILES = {
    "app/__init__.py": "",
    "app/shapes.py": "class Shape:\n    def area(self):\n        return 0\n",
    "app/draw.py": (
        "from app.shapes import Shape\n\n\n"
        "class Square(Shape):\n    def size(self):\n        return self.area()\n"
    ),
}


def test_link_cross_file_links_inheritance_and_calls_across_files(tmp_path):
    conn = _scan_without_linking(tmp_path, FILES)

    PythonAnalyzer().link_cross_file(_context(conn, tmp_path, FILES))

    assert _edges(conn, "inherits") == {("app.draw.Square", "app.shapes.Shape")}
    assert _edges(conn, "calls") == {("app.draw.Square.size", "app.shapes.Shape.area")}


TEST_FILES = {
    **FILES,
    "tests/test_shapes.py": (
        "from unittest.mock import patch\n\n"
        "from app.shapes import Shape\n\n\n"
        "@patch('app.shapes.Shape.area')\n"
        "def test_area(area):\n    assert Shape().area() == 0\n"
    ),
}


def test_link_test_evidence_indexes_tests_tested_modules_and_patch_targets(tmp_path):
    conn = _scan_without_linking(tmp_path, TEST_FILES)

    PythonAnalyzer().link_test_evidence(_context(conn, tmp_path, TEST_FILES))

    assert conn.execute("SELECT test_kind, framework FROM tests").fetchall() == [
        ("test_function", "pytest")
    ]
    assert conn.execute(
        """
        SELECT source.path, target.path FROM relationships r
        JOIN files source ON source.id = r.source_entity_id
        JOIN files target ON target.id = r.target_entity_id
        WHERE r.relationship_type = 'tests'
        """
    ).fetchall() == [("tests/test_shapes.py", "app/shapes.py")]
    assert _edges(conn, "mocks") == {
        ("tests.test_shapes.test_area", "app.shapes.Shape.area")
    }


def test_read_source_is_none_for_a_file_that_cannot_be_read(tmp_path):
    from project_mcp.plugins.python.linking import _read_source

    (tmp_path / "ok.py").write_bytes(b"x = '\xff'\n")

    assert _read_source(tmp_path / "ok.py") == "x = '�'\n"
    assert _read_source(tmp_path / "gone.py") is None
    assert _read_source(tmp_path) is None
