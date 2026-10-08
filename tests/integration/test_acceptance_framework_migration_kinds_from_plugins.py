import ast
import sys
import textwrap

import pytest

from project_mcp.plugins.registry import BUILTIN_PLUGINS, _import_object
from project_mcp.tools.symbols import find_symbol
from tests.integration.test_acceptance_core_imports_no_plugins import _core_modules

TOY_FRAMEWORK = textwrap.dedent(
    '''
    from project_mcp.plugins.descriptor import PluginDescriptor


    class ToyFramework:
        def detect(self, context):
            return True

        def enrich(self, context):
            context.conn.execute(
                """
                UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'), '$.framework_kind', 'toy_migration'
                )
                WHERE file_id IN (SELECT id FROM files WHERE path LIKE '%_gen.py')
                """
            )


    DESCRIPTOR = PluginDescriptor(
        name="toy_framework",
        version="0.1.0",
        api_version=1,
        extensions={},
        kind="framework",
        requires=("python",),
        analyzer="toy_framework:ToyFramework",
        migration_kinds=("toy_migration",),
    )
    '''
)


@pytest.fixture
def toy_framework_installed(tmp_path, monkeypatch):
    site = tmp_path / "site"
    dist_info = site / "toy_framework-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: toy-framework\nVersion: 0.1.0\n"
    )
    (dist_info / "entry_points.txt").write_text(
        "[project_mcp.plugins]\ntoy_framework = toy_framework:DESCRIPTOR\n"
    )
    (site / "toy_framework.py").write_text(TOY_FRAMEWORK)
    monkeypatch.syspath_prepend(str(site))
    yield
    sys.modules.pop("toy_framework", None)


def test_find_symbol_leaves_out_a_plugins_migration_kinds_unless_asked(
    tmp_path, toy_framework_installed
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "things.py").write_text("class Thing:\n    pass\n")
    (project / "things_gen.py").write_text("class ThingHistory:\n    pass\n")

    default = {r["name"] for r in find_symbol(project, "thing", kind="class")}
    included = {
        r["name"]
        for r in find_symbol(project, "thing", kind="class", include_migrations=True)
    }

    assert default == {"Thing"}
    assert included == {"Thing", "ThingHistory"}


def _framework_plugin_names() -> set[str]:
    descriptors = (_import_object(spec) for spec in BUILTIN_PLUGINS)
    return {d.name for d in descriptors if d.kind == "framework"}


def _strings_naming(tree: ast.Module, names: set[str]) -> list[str]:
    """String constants mentioning one of `names`, other than a plugin's module path."""
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if node.value.startswith("project_mcp.plugins."):
            continue
        if any(name in node.value.lower() for name in names):
            found.append(f"line {node.lineno}: {node.value!r}")
    return found


def test_core_strings_never_name_a_framework_plugin():
    names = _framework_plugin_names()

    violations = [
        f"{name} {string}"
        for path, name, tree in _core_modules()
        for string in _strings_naming(tree, names)
    ]

    assert violations == []
