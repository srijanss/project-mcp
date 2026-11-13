"""A file still indexed but unreadable when tests are relinked (it is being
rewritten, or briefly locked) keeps the fixture links it had."""

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.analysis import ChangedFile, LinkContext
from project_mcp.plugins.python.analyzer import PythonAnalyzer


def _project(root):
    files = {
        "app/__init__.py": "",
        "app/shapes.py": "def volume(x):\n    return x ** 3\n",
        "tests/__init__.py": "",
        "tests/conftest.py": (
            "import pytest\nfrom app.shapes import volume\n\n\n@pytest.fixture\ndef cube():\n    return volume(2)\n"
        ),
        "tests/test_cube.py": "def test_cube(cube):\n    assert cube == 8\n",
    }
    for path, source in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(source)
    conn = get_connection(root)
    run_scan(conn, root, load_config(root))
    return conn


def _relink_after_editing_shapes(conn, root):
    source = "def volume(x):\n    return x * x * x\n"
    (root / "app" / "shapes.py").write_text(source)
    path_to_file_id = dict(conn.execute("SELECT path, id FROM files"))
    PythonAnalyzer().link_test_evidence(
        LinkContext(
            conn=conn,
            project_root=root,
            source_roots=[],
            path_to_file_id=path_to_file_id,
            changed={
                "app/shapes.py": ChangedFile(
                    path_to_file_id["app/shapes.py"],
                    source,
                    PythonAnalyzer().analyze("app/shapes.py", source),
                )
            },
            added=set(),
            plugin_paths=list(path_to_file_id),
        )
    )


def _fixture_links(conn):
    return conn.execute(
        """
        SELECT source.qualified_name, target.qualified_name FROM relationships r
        JOIN symbols source ON source.id = r.source_entity_id
        JOIN symbols target ON target.id = r.target_entity_id
        WHERE r.evidence_json = '["pytest_fixture"]'
        """
    ).fetchall()


def test_a_test_keeps_its_fixture_link_while_its_file_cannot_be_read(tmp_path):
    conn = _project(tmp_path)
    assert _fixture_links(conn) == [("tests.test_cube.test_cube", "tests.conftest.cube")]
    (tmp_path / "tests" / "test_cube.py").unlink()

    _relink_after_editing_shapes(conn, tmp_path)

    assert _fixture_links(conn) == [("tests.test_cube.test_cube", "tests.conftest.cube")]


def test_a_test_keeps_its_fixture_link_while_its_conftest_cannot_be_read(tmp_path):
    conn = _project(tmp_path)
    assert _fixture_links(conn) == [("tests.test_cube.test_cube", "tests.conftest.cube")]
    (tmp_path / "tests" / "conftest.py").unlink()

    _relink_after_editing_shapes(conn, tmp_path)

    assert _fixture_links(conn) == [("tests.test_cube.test_cube", "tests.conftest.cube")]
