import pytest

from project_mcp.plugins.astro.routes import route_for


@pytest.mark.parametrize(
    "path, route, kind",
    [
        ("src/pages/index.astro", "/", "static"),
        ("src/pages/about.astro", "/about", "static"),
        ("src/pages/blog/index.astro", "/blog", "static"),
        ("src/pages/blog/[slug].astro", "/blog/[slug]", "dynamic"),
        ("src/pages/[lang]/docs/[id].astro", "/[lang]/docs/[id]", "dynamic"),
        ("src/pages/docs/[...path].astro", "/docs/[...path]", "rest"),
        ("src/pages/[...path].astro", "/[...path]", "rest"),
        ("src/pages/api/data.json.ts", "/api/data.json", "static"),
        ("src/pages/api/[id].js", "/api/[id]", "dynamic"),
    ],
)
def test_pages_and_endpoints_map_to_filesystem_routes(path, route, kind):
    assert route_for(path) == {"route": route, "route_kind": kind}


@pytest.mark.parametrize(
    "path",
    [
        "src/components/Card.astro",
        "src/pages/_hidden.astro",
        "src/pages/_private/page.astro",
        "src/pages/readme.md",
        "docs/src/pages/index.astro",
        "src/pages/styles.css",
    ],
)
def test_other_files_have_no_route(path):
    assert route_for(path) is None
