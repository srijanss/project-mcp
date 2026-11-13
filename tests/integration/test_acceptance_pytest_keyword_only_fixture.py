from project_mcp.tools.tests import get_tests_for


def test_a_test_requesting_a_fixture_as_a_keyword_only_parameter_is_listed_for_it(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "shapes.py").write_text("def volume(x):\n    return x ** 3\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / "tests" / "conftest.py").write_text(
        "import pytest\nfrom app.shapes import volume\n\n\n"
        "@pytest.fixture\ndef cube():\n    return volume(2)\n\n\n"
        "@pytest.fixture\ndef big_cube(*, cube):\n    return cube * 2\n"
    )
    (tmp_path / "tests" / "test_cube.py").write_text("def test_cube(*, big_cube):\n    assert big_cube == 16\n")

    rows = get_tests_for(tmp_path, "app.shapes.volume")

    assert [row.get("tests") for row in rows if row["test_file"] == "tests/test_cube.py"] == [
        ["tests.test_cube.test_cube"]
    ]
