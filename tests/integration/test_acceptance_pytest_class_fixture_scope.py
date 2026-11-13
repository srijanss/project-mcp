from project_mcp.tools.tests import get_tests_for


def _project(root):
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "shapes.py").write_text(
        "def volume(x):\n    return x ** 3\n\n\ndef area(x):\n    return x * x\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "test_shapes.py").write_text(
        "import pytest\nfrom app.shapes import area, volume\n\n\n"
        "@pytest.fixture\ndef shape():\n    return 1\n\n\n"
        "class TestCube:\n"
        "    @pytest.fixture\n    def shape(self):\n        return volume(2)\n\n"
        "    def test_cube(self, shape):\n        assert shape == 8\n\n\n"
        "class TestSquare:\n"
        "    @pytest.fixture\n    def shape(self):\n        return area(2)\n\n"
        "    def test_square(self, shape):\n        assert shape == 4\n\n\n"
        "def test_plain(shape):\n    assert shape == 1\n"
    )


def _tests(rows):
    return sorted(test for row in rows for test in row.get("tests") or [])


def test_a_class_fixture_is_credited_only_to_the_tests_of_its_class(tmp_path):
    _project(tmp_path)

    assert _tests(get_tests_for(tmp_path, "app.shapes.volume")) == ["tests.test_shapes.TestCube.test_cube"]
    assert _tests(get_tests_for(tmp_path, "app.shapes.area")) == ["tests.test_shapes.TestSquare.test_square"]
