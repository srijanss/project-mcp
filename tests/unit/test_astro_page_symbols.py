from project_mcp.plugins.astro.framework import AstroFramework


def _metadata(path, source="<h1 />\n"):
    analysis = AstroFramework().analyze(path, source)
    (component,) = [s for s in analysis.symbols if s["kind"] == "component"]
    return component["metadata"]


def test_a_file_under_src_pages_is_a_page_carrying_its_route():
    assert _metadata("src/pages/blog/[slug].astro") == {
        "framework_kind": "astro_page",
        "route": "/blog/[slug]",
        "route_kind": "dynamic",
    }


def test_a_page_rendering_a_slot_is_still_a_page():
    metadata = _metadata("src/pages/index.astro", "<main><slot /></main>\n")

    assert metadata["framework_kind"] == "astro_page"


def test_an_underscore_prefixed_file_under_src_pages_is_a_plain_component():
    assert _metadata("src/pages/_hidden.astro") == {"framework_kind": "astro_component"}
