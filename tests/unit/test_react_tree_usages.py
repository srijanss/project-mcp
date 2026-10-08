import pytest

from project_mcp.plugins import treesitter
from project_mcp.plugins.react import usages
from project_mcp.plugins.react.tree_usages import grammar_for, imported_names, jsx_tags

pytestmark = pytest.mark.skipif(
    treesitter.missing("tsx") is not None, reason="tree-sitter is not installed"
)


def test_imported_names_map_each_local_name_to_its_module_and_imported_name():
    source = (
        "import React from 'react';\n"
        "import Widget from './Widget';\n"
        "import Def, { Named, Other as Alias } from \"./multi\";\n"
        "import * as ns from './ns';\n"
    )

    assert imported_names(source, "tsx") == {
        "React": ("react", "default"),
        "Widget": ("./Widget", "default"),
        "Def": ("./multi", "default"),
        "Named": ("./multi", "Named"),
        "Alias": ("./multi", "Other"),
    }


def test_imported_names_span_lines_and_skip_comments_and_type_imports():
    source = (
        "import {\n  A,\n  B as C,\n  type D,\n} from './ab';\n"
        "// import Ghost from './ghost';\n"
        "import type { T } from './types';\n"
        "import type Def from './def';\n"
    )

    assert imported_names(source, "tsx") == {"A": ("./ab", "A"), "C": ("./ab", "B")}


def test_jsx_tags_are_capitalised_tags_with_their_line_numbers():
    source = "const a = (\n  <Box>\n    <Widget />\n    <ui.Button />\n    <div />\n  </Box>\n);\n"

    assert jsx_tags(source, "tsx") == [("Box", 2), ("Widget", 3)]


def test_jsx_tags_skip_comments_generics_and_comparisons():
    source = (
        "// <Ghost />\n"
        "/* <Ghost2 /> */\n"
        "const [v] = useState<Item>(null);\n"
        "const ok = a < B && c > d;\n"
        "const el = <Real />;\n"
    )

    assert jsx_tags(source, "tsx") == [("Real", 5)]


def test_tags_nested_in_expressions_and_attributes_are_found_in_source_order():
    source = (
        "const a = (\n"
        "  <List items={rows.map((r) => <Row key={r} />)} footer={<Foot />}>\n"
        "    {ok && <Shown />}\n"
        "  </List>\n"
        ");\n"
    )

    assert jsx_tags(source, "tsx") == [("List", 2), ("Row", 2), ("Foot", 2), ("Shown", 3)]


@pytest.mark.parametrize(
    "source",
    [
        "import A, { B as C } from './x';\nconst e = (\n  <A>\n    <C />\n  </A>\n);\n",
        "// <Ghost />\nconst e = <Real a={<Inner />} />;\n",
    ],
)
def test_the_tree_and_regex_parsers_agree(source):
    assert imported_names(source, "tsx") == usages.imported_names(source)
    assert jsx_tags(source, "tsx") == usages.jsx_tags(source)


def test_the_grammar_follows_the_file_suffix():
    assert grammar_for("src/a.ts") == "typescript"
    assert grammar_for("src/a.tsx") == "tsx"
    assert grammar_for("src/a.jsx") == "tsx"
    assert grammar_for("src/a.js") == "javascript"
    assert grammar_for("src/a.mjs") == "javascript"
    assert grammar_for("src/a.cjs") == "javascript"
