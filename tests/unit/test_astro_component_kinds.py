from project_mcp.plugins.astro.framework import AstroFramework


def _component(path, source):
    analysis = AstroFramework().analyze(path, source)
    (component,) = [s for s in analysis.symbols if s["kind"] == "component"]
    return component


def test_a_component_symbol_is_named_after_the_file_and_spans_it():
    component = _component("src/components/Card.astro", "---\n---\n<div />\n")

    assert component["name"] == "Card"
    assert component["qualified_name"] == "src.components.Card.Card"
    assert (component["start_line"], component["end_line"]) == (1, 3)
    assert component["metadata"] == {"framework_kind": "astro_component"}


def test_files_under_src_layouts_are_layouts():
    kind = _component("src/layouts/Base.astro", "<html />\n")["metadata"]["framework_kind"]

    assert kind == "astro_layout"


def test_files_rendering_a_slot_are_layouts():
    for template in ("<main><slot /></main>", '<slot name="head">', "<slot>fallback</slot>"):
        kind = _component("src/components/Box.astro", template)["metadata"]["framework_kind"]
        assert kind == "astro_layout", template


def test_a_slot_mentioned_only_in_the_frontmatter_does_not_make_a_layout():
    source = '---\nconst html = "<slot />";\n---\n<div />\n'

    kind = _component("src/components/Box.astro", source)["metadata"]["framework_kind"]

    assert kind == "astro_component"


def test_a_layouts_directory_outside_src_does_not_make_a_layout():
    kind = _component("docs/layouts/Box.astro", "<div />\n")["metadata"]["framework_kind"]

    assert kind == "astro_component"
