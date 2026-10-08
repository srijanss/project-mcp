from project_mcp.plugins.treesitter import parse
from tests.integration.test_acceptance_core_imports_no_plugins import _core_modules, _imported_modules

SOURCE = """\
function greet() {}

class Greeter {
  hello() {}
}
"""


def _find(node, node_type):
    if node.type == node_type:
        return node
    for child in node.children:
        found = _find(child, node_type)
        if found is not None:
            return found
    return None


def test_parses_source_with_named_grammar_and_exposes_line_spans():
    tree = parse(SOURCE, "javascript")

    greeter = _find(tree, "class_declaration")

    assert (greeter.start_line, greeter.end_line) == (3, 5)
    assert greeter.field("name").text == "Greeter"


def test_core_never_imports_the_tree_sitter_helper():
    importers = [
        name
        for path, name, tree in _core_modules()
        if "project_mcp.plugins.treesitter" in _imported_modules(tree, name, path.name == "__init__.py")
    ]

    assert importers == []
