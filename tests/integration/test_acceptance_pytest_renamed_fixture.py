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
        "import pytest\nfrom app.shapes import volume\n\n\n"
        "@pytest.fixture(name='cube')\ndef make_cube():\n    return volume(2)\n"
    )
    (root / "tests" / "test_shapes.py").write_text(
        "import pytest\nfrom app.shapes import area\n\n\n"
        "@pytest.fixture(name='square')\ndef make_square():\n    return area(2)\n\n\n"
        "def test_cube(cube):\n    assert cube == 8\n\n\n"
        "def test_square(square):\n    assert square == 4\n\n\n"
        "def test_by_function_name(make_cube, make_square):\n    pass\n"
    )


def _tests(rows):
    return sorted(test for row in rows if row["test_file"] == "tests/test_shapes.py" for test in row.get("tests") or [])


def test_a_test_requesting_a_fixture_by_its_registered_name_is_listed_for_it(tmp_path):
    _project(tmp_path)

    assert _tests(get_tests_for(tmp_path, "app.shapes.volume")) == ["tests.test_shapes.test_cube"]
    assert _tests(get_tests_for(tmp_path, "app.shapes.area")) == ["tests.test_shapes.test_square"]
