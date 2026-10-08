from project_mcp.plugins.react.usages import (
    import_candidates,
    imported_names,
    jsx_tags,
    names_outside_tags,
)


def test_imported_names_map_each_local_name_to_its_module_and_imported_name():
    source = (
        "import React from 'react';\n"
        "import Widget from './Widget';\n"
        "import Def, { Named, Other as Alias } from \"./multi\";\n"
        "import * as ns from './ns';\n"
    )

    assert imported_names(source) == {
        "React": ("react", "default"),
        "Widget": ("./Widget", "default"),
        "Def": ("./multi", "default"),
        "Named": ("./multi", "Named"),
        "Alias": ("./multi", "Other"),
    }


def test_imported_names_span_lines_and_skip_comments_and_type_imports():
    source = (
        "import {\n  A,\n  B as C,\n} from './ab';\n"
        "// import Ghost from './ghost';\n"
        "import type { T } from './types';\n"
    )

    assert imported_names(source) == {"A": ("./ab", "A"), "C": ("./ab", "B")}


def test_jsx_tags_are_capitalised_tags_with_their_line_numbers():
    source = "const a = (\n  <Box>\n    <Widget />\n    <ui.Button />\n    <div />\n  </Box>\n);\n"

    assert jsx_tags(source) == [("Box", 2), ("Widget", 3)]


def test_jsx_tags_skip_comments_generics_and_comparisons():
    source = (
        "// <Ghost />\n"
        "/* <Ghost2 /> */\n"
        "const [v] = useState<Item>(null);\n"
        "const ok = a < B && c > d;\n"
        "const el = <Real />;\n"
    )

    assert jsx_tags(source) == [("Real", 5)]


def test_import_candidates_resolve_relative_specifiers_only():
    assert import_candidates("src/App.tsx", "react") == []
    assert import_candidates("src/App.tsx", "./Widget") == [
        "src/Widget.ts",
        "src/Widget.tsx",
        "src/Widget.js",
        "src/Widget.jsx",
        "src/Widget/index.ts",
        "src/Widget/index.tsx",
        "src/Widget/index.js",
        "src/Widget/index.jsx",
    ]
    assert import_candidates("src/a/App.tsx", "../Widget.tsx") == ["src/Widget.tsx"]


def test_names_outside_tags_are_capitalised_identifiers_not_in_tag_position():
    source = (
        "function Row() {\n  return <li />;\n}\n\n"
        "export function List({ Row }) {\n"
        "  // Ghost is only mentioned in a comment\n"
        "  return <ul><Row></Row><ui.Cell /></ul>;\n"
        "}\n"
    )

    assert names_outside_tags(source, 5, 8) == {"List", "Row"}
    assert names_outside_tags(source, 7, float("inf")) == set()
