import pytest

from project_mcp.plugins.javascript.parser import parse_js_source
from project_mcp.plugins.javascript.tree_parser import parse_js_tree

JS_SOURCE = """\
import React from 'react';

function topLevel(x) {
  return x;
}

export default function Page() {
  return (
    <main />
  );
}

export const Card = async (props) => {
  return <div>{props.title}</div>;
};
const helper = value => value + 1;
// function commented() {}
let notAFunction = 1;

class Widget {
  constructor(label) {
    this.label = label;
  }

  render() {
    return topLevel(this.label);
  }
}
"""

TSX_SOURCE = """\
import React from 'react';

export function Widget(props: { label: string }) {
  return <div>{props.label}</div>;
}

export const helperValue = 1;
"""


@pytest.mark.parametrize(
    ("path", "source", "grammar"),
    [("app/widget.js", JS_SOURCE, "javascript"), ("src/Widget.tsx", TSX_SOURCE, "tsx")],
)
def test_parse_js_tree_finds_the_symbols_the_regex_parser_finds(path, source, grammar):
    def found(symbols):
        return sorted((s["qualified_name"], s["kind"], s["start_line"]) for s in symbols)

    assert found(parse_js_tree(path, source, grammar)) == found(parse_js_source(path, source))


def test_parse_js_tree_marks_components_by_their_own_jsx_return():
    source = """\
export const Badge = () => <span />;
function Label() {
  // return <span />
  return "label";
}
function Wrapper() {
  const inner = () => {
    return <div />;
  };
  return inner;
}
"""
    kinds = {s["qualified_name"]: s["kind"] for s in parse_js_tree("ui.jsx", source, "tsx")}

    assert kinds == {
        "ui": "module",
        "ui.Badge": "component",
        "ui.Label": "function",
        "ui.Wrapper": "function",
        "ui.Wrapper.inner": "function",
    }


def test_parse_js_tree_gives_each_declaration_its_end_line():
    spans = {
        s["qualified_name"]: (s["start_line"], s["end_line"])
        for s in parse_js_tree("app/widget.js", JS_SOURCE, "javascript")
    }

    assert spans["app.widget.topLevel"] == (3, 5)
    assert spans["app.widget.Card"] == (13, 15)
    assert spans["app.widget.Widget"] == (20, 28)
    assert spans["app.widget.Widget.render"] == (25, 27)


def test_parse_js_tree_finds_typescript_interfaces_enums_and_type_aliases():
    source = """\
export interface Props {
  label: string;
}
enum Color { Red }
export type Id = string;
"""
    found = {
        (s["qualified_name"], s["kind"], s["start_line"], s["end_line"])
        for s in parse_js_tree("types.ts", source, "typescript")
    }

    assert found >= {
        ("types.Props", "interface", 1, 3),
        ("types.Color", "enum", 4, 4),
        ("types.Id", "type_alias", 5, 5),
    }


def test_parse_js_tree_qualifies_nested_functions_under_their_parent():
    source = """\
function outer() {
  function inner() {
    const leaf = () => 1;
  }
}
class Box {
  open() {
    const peek = function () {};
  }
}
"""
    names = {s["qualified_name"] for s in parse_js_tree("nest.js", source, "javascript")}

    assert {"nest.outer.inner", "nest.outer.inner.leaf", "nest.Box.open.peek"} <= names
