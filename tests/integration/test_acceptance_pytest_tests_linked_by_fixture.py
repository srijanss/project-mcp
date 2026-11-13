from project_mcp.tools.tests import get_tests_for


def _project(root):
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "shapes.py").write_text(
        "def volume(x):\n    return x ** 3\n\n\ndef area(x):\n    return x * x\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "conftest.py").write_text(
        "import pytest\nfrom app.shapes import volume\n\n\n@pytest.fixture\ndef cube():\n    return volume(2)\n"
    )
    (root / "tests" / "test_cube.py").write_text("def test_cube(cube):\n    assert cube == 8\n")
    (root / "tests" / "test_square.py").write_text(
        "import pytest\nfrom app.shapes import area\n\n\n@pytest.fixture\ndef square():\n    return area(2)\n\n\n"
        "def test_square(square):\n    assert square == 4\n"
    )


def _tests(rows, test_file):
    return next((row.get("tests") for row in rows if row["test_file"] == test_file), None)


def test_a_test_requesting_a_conftest_fixture_that_calls_a_symbol_is_listed_for_it(tmp_path):
    _project(tmp_path)

    assert _tests(get_tests_for(tmp_path, "app.shapes.volume"), "tests/test_cube.py") == ["tests.test_cube.test_cube"]


def test_a_test_requesting_a_fixture_of_its_own_module_that_calls_a_symbol_is_listed_for_it(tmp_path):
    _project(tmp_path)

    assert _tests(get_tests_for(tmp_path, "app.shapes.area"), "tests/test_square.py") == ["tests.test_square.test_square"]
