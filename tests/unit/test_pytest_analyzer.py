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
        from project_mcp.analyzers.python.pytest_analyzer import (
            build_test_relationships,
        )

        test_source = """\
from mymodule import my_function

def test_my_function():
    unrelated = 5
    expected = 10
    result = my_function()
    assert result == expected
"""
        relationships = build_test_relationships("tests/test_mymodule.py", test_source)

        # "unrelated", "expected", and "result" are local names, not source
        # module references, and must not be reported as separate
        # (false-positive) test-relationship targets.
        assert len(relationships) == 1
        assert relationships[0]["target_module"] == "mymodule"
        assert relationships[0]["confidence"] == "high"
        assert "direct_import" in relationships[0]["evidence"]

    def test_naming_convention_fallback_when_no_imports(self):
        """Fall back to naming-convention evidence when no import exists."""
        from project_mcp.analyzers.python.pytest_analyzer import (
            build_test_relationships,
        )

        test_source = """\
def test_widget_creation():
    assert True
"""
        relationships = build_test_relationships("tests/test_widgets.py", test_source)

        assert len(relationships) == 1
        assert relationships[0]["target_module"] == "widgets"
        assert relationships[0]["confidence"] == "low"
        assert relationships[0]["evidence"] == ["naming_convention"]

    def test_merges_multiple_imports_from_the_same_module(self):
        """Two import statements from the same module -> one relationship."""
        from project_mcp.analyzers.python.pytest_analyzer import (
            build_test_relationships,
        )

        test_source = """\
from mymodule import my_function
from mymodule import other_function

def test_my_function():
    assert my_function()
    assert other_function()
"""
        relationships = build_test_relationships("tests/test_mymodule.py", test_source)

        assert len(relationships) == 1
        assert relationships[0]["target_module"] == "mymodule"
        assert relationships[0]["confidence"] == "high"
        assert relationships[0]["evidence"] == ["direct_import"]

    def test_reports_each_distinct_imported_module_once(self):
        """Imports from two distinct modules -> two separate relationships."""
        from project_mcp.analyzers.python.pytest_analyzer import (
            build_test_relationships,
        )

        test_source = """\
from mymodule import my_function
from othermodule import other_function

def test_things():
    assert my_function()
    assert other_function()
"""
        relationships = build_test_relationships("tests/test_mymodule.py", test_source)

        target_modules = {r["target_module"] for r in relationships}
        assert target_modules == {"mymodule", "othermodule"}

    def test_relative_import_is_not_high_confidence(self):
        """A relative import (level > 0) can't be resolved without package
        context, so it must not be treated as high-confidence direct-import
        evidence — fall back to naming-convention evidence instead."""
        from project_mcp.analyzers.python.pytest_analyzer import (
            build_test_relationships,
        )

        test_source = """\
from .mymodule import my_function

def test_my_function():
    assert my_function()
"""
        relationships = build_test_relationships("tests/test_mymodule.py", test_source)

        assert len(relationships) == 1
        assert relationships[0]["target_module"] == "mymodule"
        assert relationships[0]["confidence"] == "low"
        assert relationships[0]["evidence"] == ["naming_convention"]

    def test_ignores_non_test_files(self):
        """A regular (non-test) Python file yields no test relationships."""
        from project_mcp.analyzers.python.pytest_analyzer import (
            build_test_relationships,
        )

        source = """\
from mymodule import my_function

def use_it():
    return my_function()
"""
        relationships = build_test_relationships("app/importer.py", source)

        assert relationships == []


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
