from project_mcp.plugins.python.analyzer import PythonAnalyzer

SOURCE = '''import os
from app import models, views
from .util import helper
from ..up import far


class Base:
    kind = "x"

    def run(self):
        return self.step()

    def step(self):
        return Base.kind


class Child(Base, mixins.Thing):
    def go(self):
        helper()
        self.run()
        return self.kind


def helper():
    return compute()


def compute():
    return 1
'''


def test_analyze_returns_symbols_with_class_bases_as_metadata():
    analysis = PythonAnalyzer().analyze("app/shapes.py", SOURCE)

    assert [
        (s["qualified_name"], s["kind"], s.get("metadata")) for s in analysis.symbols
    ] == [
        ("app.shapes", "module", None),
        ("app.shapes.Base", "class", {"bases": []}),
        ("app.shapes.Base.kind", "field", None),
        ("app.shapes.Base.run", "method", None),
        ("app.shapes.Base.step", "method", None),
        ("app.shapes.Child", "class", {"bases": ["Base", "mixins.Thing"]}),
        ("app.shapes.Child.go", "method", None),
        ("app.shapes.helper", "function", None),
        ("app.shapes.compute", "function", None),
    ]
    assert PythonAnalyzer().analyze("app/broken.py", "def (:\n").symbols == []


def test_analyze_links_same_file_inheritance_calls_and_references():
    analysis = PythonAnalyzer().analyze("app/shapes.py", SOURCE)

    assert analysis.symbol_edges == [
        ("app.shapes.Child", "app.shapes.Base", "inherits"),
        ("app.shapes.Child.go", "app.shapes.helper", "calls"),
        ("app.shapes.helper", "app.shapes.compute", "calls"),
        ("app.shapes.Base.run", "app.shapes.Base.step", "calls"),
        ("app.shapes.Child.go", "app.shapes.Base.run", "calls"),
        ("app.shapes.Base.step", "app.shapes.Base.kind", "references"),
    ]


def test_analyze_makes_relative_imports_absolute_and_drops_unresolvable_ones():
    analysis = PythonAnalyzer().analyze("app/shapes.py", SOURCE)

    assert analysis.imports == [
        ("os", ()),
        ("app", ("models", "views")),
        ("app.util", ("helper",)),
    ]


def test_resolve_import_maps_a_module_and_its_imported_names_to_files():
    analyzer = PythonAnalyzer()

    candidates = analyzer.resolve_import("main.py", ("app", ("models", "views")))

    assert analyzer.resolve_import("main.py", ("app.util", ())) == ["app/util/__init__.py", "app/util.py"]
    assert [c for c in candidates if not c.endswith("__init__.py")] == [
        "app/models.py",
        "app/views.py",
        "app.py",
    ]


def test_is_test_file_recognises_test_dirs_and_test_name_affixes():
    from pathlib import Path

    analyzer = PythonAnalyzer()

    assert [
        analyzer.is_test_file(Path(path))
        for path in (
            "tests/conftest.py",
            "app/test/helpers.py",
            "app/test_models.py",
            "app/models_test.py",
            "app/models.py",
            "app/testing.py",
        )
    ] == [True, True, True, True, False, False]


def test_analyze_keeps_the_full_parse_for_cross_file_linking():
    analysis = PythonAnalyzer().analyze("app/shapes.py", SOURCE)

    assert analysis.extra["typed_calls"] == []
    assert analysis.extra["calls"][0]["caller"] == "app.shapes.Child.go"
    assert [imp["module"] for imp in analysis.extra["imports"]] == [
        "os",
        "app",
        "app.util",
        "up",
    ]


def test_builtin_registry_serves_the_python_analyzer():
    from project_mcp.plugins.registry import builtin_registry

    assert isinstance(builtin_registry().analyzer_for("python"), PythonAnalyzer)


def test_python_analyzer_keys_dependencies_by_normalized_name_and_reads_uv_lock(tmp_path):
    analyzer = PythonAnalyzer()
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "Requests"\nversion = "2.32.3"\n')

    assert analyzer.dependency_key("Typing_Extensions") == analyzer.dependency_key("typing-extensions")
    assert analyzer.undeclared_dependency(tmp_path, "requests") == {
        "name": "requests",
        "ecosystem": "python",
        "version": "2.32.3",
        "version_status": "resolved",
    }
    assert analyzer.undeclared_dependency(tmp_path, "missing") is None
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["flask"]\n')
    assert analyzer.undeclared_dependency(tmp_path, "requests") is None


def test_declared_dependencies_skip_requirements_includes_resolving_outside_the_root(tmp_path):
    from project_mcp.plugins.python.dependencies import declared_dependencies

    project = tmp_path / "project"
    (project / "reqs").mkdir(parents=True)
    (tmp_path / "outside.txt").write_text("leaked==1\n")
    (project / "reqs" / "base.txt").write_text("httpx>=0.27\n")
    (project / "requirements.txt").write_text(
        f"-r {tmp_path / 'outside.txt'}\n"
        "--requirement ../outside.txt\n"
        "-r reqs/../reqs/base.txt\n"
    )

    assert [d["name"] for d in declared_dependencies(project)] == ["httpx"]


def test_resolve_import_prefers_a_package_to_a_module_of_the_same_name():
    analyzer = PythonAnalyzer()

    assert analyzer.resolve_import("main.py", ("pkg", ())) == ["pkg/__init__.py", "pkg.py"]
    assert analyzer.resolve_import("main.py", ("app", ("models",))) == [
        "app/models/__init__.py",
        "app/models.py",
        "app/__init__.py",
        "app.py",
    ]
