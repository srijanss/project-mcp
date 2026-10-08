from project_mcp.tools.context_packs import get_context_for_feature
from project_mcp.tools.symbols import find_symbol

FILES = {
    "package.json": '{"dependencies": {"astro": "^4.0.0"}}',
    "src/pages/blog/[slug].astro": "<h1>post</h1>\n",
    "src/pages/index.astro": "<h1>home</h1>\n",
    "src/components/Card.astro": "<div />\n",
}


def _project(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)


def test_find_symbol_accepts_a_route_path_and_returns_its_page(tmp_path):
    _project(tmp_path)

    matches = find_symbol(tmp_path, "/blog/[slug]", kind="component")

    assert [(m["file"], m["name"]) for m in matches] == [("src/pages/blog/[slug].astro", "[slug]")]


def test_get_context_for_feature_accepts_a_route_path(tmp_path):
    _project(tmp_path)

    context = get_context_for_feature(tmp_path, "/blog/[slug]")

    assert "src/pages/blog/[slug].astro" in context["recommended_files_to_open"]


def test_the_root_route_matches_only_the_index_page(tmp_path):
    _project(tmp_path)

    matches = find_symbol(tmp_path, "/", kind="component")

    assert [m["file"] for m in matches] == ["src/pages/index.astro"]
