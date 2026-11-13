from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, run_scan
from project_mcp.tools.tests import get_tests_for


def _project(root):
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "shapes.py").write_text("def volume(x):\n    return x ** 3\n")
    (root / "conftest.py").write_text(
        "import pytest\nfrom app.shapes import volume\n\n\n"
        "@pytest.fixture\ndef cube():\n    return volume(2)\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("")
    # Overrides the root fixture, requesting it under the same name.
    (root / "tests" / "conftest.py").write_text(
        "import pytest\n\n\n@pytest.fixture\ndef cube(cube):\n    return cube + 1\n"
    )
    (root / "tests" / "test_cube.py").write_text("def test_cube(cube):\n    assert cube == 9\n")


def _tests(rows):
    return sorted(test for row in rows if row["test_file"] == "tests/test_cube.py" for test in row.get("tests") or [])


def test_a_test_reaching_a_root_conftest_fixture_through_an_override_is_listed_for_what_it_calls(tmp_path):
    _project(tmp_path)

    assert _tests(get_tests_for(tmp_path, "app.shapes.volume")) == ["tests.test_cube.test_cube"]


def test_an_index_written_before_root_conftest_files_were_tests_is_rebuilt(tmp_path):
    _project(tmp_path)
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, config)
    # What an index left by schema 9 code looks like: the root conftest.py
    # is a source file.
    conn.execute("UPDATE files SET file_kind = 'source' WHERE path = 'conftest.py'")
    conn.execute("UPDATE index_metadata SET value = '9' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    conn = get_connection(tmp_path)
    ensure_fresh_index(conn, tmp_path, config)
    conn.close()

    assert _tests(get_tests_for(tmp_path, "app.shapes.volume")) == ["tests.test_cube.test_cube"]
