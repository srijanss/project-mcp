import pytest

from project_mcp.plugins.javascript.parser import parse_js_source
from project_mcp.plugins.javascript.tree_parser import parse_js_calls, parse_js_tree

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


def test_parse_js_calls_resolves_static_calls_to_the_innermost_known_function():
    source = """\
function helper() {}
function run() {
  function helper() {}
  helper();
  [1].map((n) => format(n));
  this.missing();
  obj.helper();
  lookup[name]();
}
function format() {}
class Job {
  start() {
    this.step();
    this.step();
  }
  step() {}
}
"""
    symbols = parse_js_tree("jobs.js", source, "javascript")

    assert parse_js_calls("jobs.js", source, "javascript", symbols) == [
        ("jobs.run", "jobs.run.helper", "calls"),
        ("jobs.run", "jobs.format", "calls"),
        ("jobs.Job.start", "jobs.Job.step", "calls"),
    ]


@pytest.mark.parametrize(
    "grammar, body",
    [
        ("javascript", "function run(helper) { helper(); }"),
        ("javascript", "function run({ helper }) { helper(); }"),
        ("javascript", "function run([first, ...helper]) { helper(); }"),
        ("javascript", "function run(helper = 1) { helper(); }"),
        ("javascript", "const run = helper => helper();"),
        ("javascript", "function run() { let helper; helper(); }"),
        ("javascript", "function run() { const { a: helper } = deps; helper(); }"),
        ("javascript", "function run() { try {} catch (helper) { helper(); } }"),
        ("javascript", "function run(helper) { [1].map(() => helper()); }"),
        ("typescript", "function run(helper: () => void) { helper(); }"),
        ("typescript", "function run(helper?: () => void) { helper(); }"),
        ("typescript", "class Job { constructor(private helper: () => void) { helper(); } }"),
    ],
)
def test_parse_js_calls_leaves_out_calls_through_local_bindings(grammar, body):
    source = f"function helper() {{}}\n{body}\n"
    symbols = parse_js_tree("jobs.js", source, grammar)

    assert parse_js_calls("jobs.js", source, grammar, symbols) == []


def test_parse_js_tree_finds_a_named_function_wrapped_in_a_default_export():
    source = (
        "export default memo(function Badge() {\n"
        "  const label = () => 'b';\n"
        "  return <b />;\n"
        "});\n"
    )
    symbols = {s["qualified_name"]: s for s in parse_js_tree("badge.tsx", source, "tsx")}

    assert symbols["badge.Badge"]["kind"] == "component"
    assert (symbols["badge.Badge"]["start_line"], symbols["badge.Badge"]["end_line"]) == (1, 4)
    assert "badge.Badge.label" in symbols


def test_parse_js_tree_skips_comments_before_a_wrapped_default_function():
    source = "export default memo(/* pure */ function Badge() {\n  return <b />;\n});\n"
    symbols = {s["qualified_name"]: s for s in parse_js_tree("badge.tsx", source, "tsx")}

    assert symbols["badge.Badge"]["kind"] == "component"


def test_parse_js_calls_attributes_calls_to_a_wrapped_default_function():
    source = """\
function helper() {}

function each(items) {
  items.map(function visit() {
    helper();
  });
}

export default memo(function Badge() {
  const inner = () => 1;
  helper();
  inner();
});
"""
    symbols = parse_js_tree("badge.js", source, "javascript")

    assert parse_js_calls("badge.js", source, "javascript", symbols) == [
        ("badge.each", "badge.helper", "calls"),
        ("badge.Badge", "badge.helper", "calls"),
        ("badge.Badge", "badge.Badge.inner", "calls"),
    ]
