import pytest

from project_mcp.plugins import treesitter
from project_mcp.plugins.react import usages
from project_mcp.plugins.react.tree_usages import (
    default_export_name,
    export_aliases,
    grammar_for,
    imported_names,
    jsx_tags,
    shadowed_tags,
)

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


def test_imported_names_ignore_comments_inside_an_import_list():
    source = "import { /* row */ A, // note\n  B as C /* end */ } from './ab';\n"

    assert imported_names(source, "tsx") == {"A": ("./ab", "A"), "C": ("./ab", "B")}


def test_default_export_name_follows_wrapper_calls_across_lines():
    assert default_export_name("export default memo(\n  Badge,\n);\n", "tsx") == "Badge"
    assert default_export_name(
        "export default connect(\n  (state) => state.card,\n)(Card);\n", "tsx"
    ) == "Card"
    assert default_export_name("export default withRouter(memo(Nav));\n", "javascript") == "Nav"


def test_default_export_name_reads_default_function_and_class_declarations():
    source = (
        "export function Helper() {}\n"
        "export default async function Main() {\n  return <main />;\n}\n"
    )

    assert default_export_name(source, "tsx") == "Main"
    assert default_export_name("export default class Page {}\n", "typescript") == "Page"
    assert default_export_name("export default Plain;\n", "javascript") == "Plain"


def test_default_export_name_reads_an_export_list_alias_and_ignores_comments():
    source = (
        "// export default Old;\n"
        "export { Other, Inner as default };\n"
    )

    assert default_export_name(source, "tsx") == "Inner"
    assert default_export_name("/* export default Gone; */\nexport { A };\n", "tsx") is None


def test_default_export_name_reads_a_named_function_inside_a_wrapper():
    source = "export default memo(function Badge() {\n  return <b />;\n});\n"

    assert default_export_name(source, "tsx") == "Badge"
    assert default_export_name("export default memo(function () {});\n", "tsx") is None


def test_default_export_name_skips_comments_before_a_wrapped_argument():
    assert default_export_name("export default memo(/* note */ Badge);\n", "tsx") == "Badge"
    source = "export default memo(\n  // the card\n  function Card() {\n    return <b />;\n  },\n);\n"
    assert default_export_name(source, "tsx") == "Card"


def test_shadowed_tags_are_tags_named_by_an_enclosing_local_binding():
    source = """\
function Row() {
  return <li />;
}

export function List({ Row, Cell = Row }) {
  const Icon = pick();
  return <ul><Row /><Icon /><Cell /></ul>;
}

export function Table({ rows }) {
  return <table>{rows.map((Item) => <Item />)}<Row /></table>;
}
"""

    assert shadowed_tags(source, "tsx") == {("Row", 7), ("Icon", 7), ("Cell", 7), ("Item", 11)}


def test_shadowed_tags_can_include_function_valued_variables_declared_in_an_enclosing_scope():
    source = """\
test('stubs', () => {
  const Button = () => null;
  function Icon() {
    return null;
  }
  render(<div><Button /><Icon /></div>);
});
render(<Button />);
"""

    assert shadowed_tags(source, "tsx") == set()
    assert shadowed_tags(source, "tsx", functions=True) == {("Button", 6), ("Icon", 6)}


def test_export_aliases_map_each_renamed_export_to_its_local_name():
    source = """\
function Button() {}
function Card() {}
export { Button as Primary, Card, Card as Panel };
export { Button as default };
export { Other as Elsewhere } from './other';
// export { Card as Commented };
"""

    assert export_aliases(source, "tsx") == {"Primary": "Button", "Panel": "Card"}
    assert export_aliases("export function Plain() {}\n", "tsx") == {}
