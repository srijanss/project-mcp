from project_mcp.tools.tests import get_tests_for


def _project(root):
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "shapes.py").write_text("def volume(x):\n    return x ** 3\n")
    (root / "tests" / "solids").mkdir(parents=True)
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "conftest.py").write_text(
        "import pytest\nfrom app.shapes import volume\n\n\n"
        "@pytest.fixture\ndef cube():\n    return volume(2)\n"
    )
    (root / "tests" / "solids" / "__init__.py").write_text("")
    # Overrides the outer fixture, requesting it under the same name.
    (root / "tests" / "solids" / "conftest.py").write_text(
        "import pytest\n\n\n@pytest.fixture\ndef cube(cube):\n    return cube + 1\n"
    )
    (root / "tests" / "solids" / "test_cube.py").write_text("def test_cube(cube):\n    assert cube == 9\n")


def _tests(rows):
    return sorted(
        test for row in rows if row["test_file"] == "tests/solids/test_cube.py" for test in row.get("tests") or []
    )


def test_a_test_using_a_conftest_override_is_listed_for_what_the_overridden_fixture_calls(tmp_path):
    _project(tmp_path)

    assert _tests(get_tests_for(tmp_path, "app.shapes.volume")) == ["tests.solids.test_cube.test_cube"]
