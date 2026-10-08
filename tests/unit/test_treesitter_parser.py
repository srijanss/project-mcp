import pytest

from project_mcp.plugins.treesitter import parse


def test_parse_returns_the_grammar_root_node_with_one_based_lines():
    root = parse("let a = 1;\nlet b = 2;\n", "javascript")

    assert root.type == "program"
    assert (root.start_line, root.end_line) == (1, 2)


def test_parse_uses_the_named_grammar():
    root = parse("fn main() {}\n", "rust")

    assert root.type == "source_file"


def test_nodes_expose_named_children_fields_and_text():
    root = parse("fn main() {}\n\nstruct Point;\n", "rust")

    function, struct = root.children

    assert [function.type, struct.type] == ["function_item", "struct_item"]
    assert function.field("name").text == "main"
    assert (struct.start_line, struct.end_line) == (3, 3)


def test_parse_rejects_an_unknown_grammar_by_name():
    with pytest.raises(ValueError, match="cobol"):
        parse("", "cobol")
