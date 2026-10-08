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
    def key(symbol):
        return symbol["qualified_name"]

    assert sorted(parse_js_tree(path, source, grammar), key=key) == sorted(
        parse_js_source(path, source), key=key
    )


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
    kinds = {s["name"]: s["kind"] for s in parse_js_tree("ui.jsx", source, "tsx")}

    assert kinds == {"ui": "module", "Badge": "component", "Label": "function", "Wrapper": "function"}
