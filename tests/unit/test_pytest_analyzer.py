"""Tests for pytest test discovery and analysis."""

import pytest

from project_mcp.analyzers.python.pytest_analyzer import (
    classify_test_type,
    discover_tests,
    extract_test_imports,
)


class TestPytestDiscovery:
    """Discover pytest test functions and classes in Python source files."""

    def test_find_test_functions_in_file(self):
        """Discover test_* functions in a Python file."""
        source = """\
def test_something():
    assert True

def test_another():
    assert False
"""
        tests = discover_tests("tests/test_example.py", source)
        assert len(tests) == 2
        assert tests[0]["name"] == "test_something"
        assert tests[0]["kind"] == "test_function"
        assert tests[1]["name"] == "test_another"
        assert tests[1]["kind"] == "test_function"

    def test_find_test_classes_in_file(self):
        """Discover Test* classes with test_* methods."""
        source = """\
class TestExample:
    def test_method_one(self):
        assert True

    def test_method_two(self):
        assert False

    def helper_not_a_test(self):
        pass
"""
        tests = discover_tests("tests/test_example.py", source)
        assert len(tests) == 3  # 1 class + 2 methods
        assert tests[0]["kind"] == "test_class"
        assert tests[0]["name"] == "TestExample"
        assert tests[1]["kind"] == "test_method"
        assert tests[1]["name"] == "test_method_one"
        assert tests[2]["kind"] == "test_method"
        assert tests[2]["name"] == "test_method_two"

    def test_extract_test_function_details(self):
        """Extract name, location, and fixtures from test function."""
        source = """\
def test_with_location():
    pass
"""
        tests = discover_tests("tests/test_example.py", source)
        assert len(tests) == 1
        test = tests[0]
        assert test["name"] == "test_with_location"
        assert test["qualified_name"] == "tests.test_example.test_with_location"
        assert "start_line" in test
        assert "end_line" in test
        assert test["start_line"] > 0

    def test_ignore_non_test_files(self):
        """Skip files that don't match test file naming conventions."""
        source = """\
def test_something():
    pass
"""
        # Non-test file
        tests = discover_tests("src/example.py", source)
        assert len(tests) == 0

        # Test file
        tests = discover_tests("tests/test_example.py", source)
        assert len(tests) == 1


class TestTestSourceAssociation:
    """Associate discovered tests with source modules they test."""

    def test_direct_import_association(self):
        """Test imports source module directly: test knows its target."""
        from project_mcp.analyzers.python.pytest_analyzer import extract_test_imports

        test_source = """\
from mymodule import my_function

def test_my_function():
    assert my_function()
"""
        imports = extract_test_imports("tests/test_mymodule.py", test_source)
        module_names = [imp["module"] for imp in imports if imp.get("module")]
        assert "mymodule" in module_names

    def test_symbol_reference_association(self):
        """Test calls a function from source: infer association via call."""
        from project_mcp.analyzers.python.pytest_analyzer import find_test_source_refs

        test_source = """\
from mymodule import my_function

def test_my_function():
    result = my_function()
    assert result == expected
"""
        # Find what this test references from source modules
        refs = find_test_source_refs("tests/test_mymodule.py", test_source)
        # Should find references to my_function from mymodule
        assert any("my_function" in str(ref) for ref in refs)

    def test_naming_convention_association(self):
        """Test name matches source: test_foo.py tests foo.py by convention."""
        from project_mcp.analyzers.python.pytest_analyzer import infer_tested_module

        # test_foo.py -> foo module by naming convention
        assert infer_tested_module("tests/test_foo.py") == "foo"
        assert infer_tested_module("test_models.py") == "models"

        # foo_test.py -> foo module
        assert infer_tested_module("tests/models_test.py") == "models"

    def test_no_false_positive_association(self):
        """Avoid associating unrelated tests to source modules."""
        pytest.skip("GREEN: implement test relationship builder")


class TestPyTestKinds:
    """Classify pytest test structures (unit, integration, etc.)."""

    def test_identify_unit_test(self):
        """Mark test in tests/unit/ as unit test."""
        assert classify_test_type("tests/unit/test_example.py") == "unit"
        assert classify_test_type("test_example.py") == "unit"

    def test_identify_integration_test(self):
        """Mark test in tests/integration/ as integration test."""
        assert classify_test_type("tests/integration/test_api.py") == "integration"
        assert classify_test_type("test_integration_api.py") == "integration"

    def test_identify_e2e_test(self):
        """Mark test in tests/e2e/ as end-to-end test."""
        assert classify_test_type("tests/e2e/test_flow.py") == "e2e"
        assert classify_test_type("test_e2e_flow.py") == "e2e"
