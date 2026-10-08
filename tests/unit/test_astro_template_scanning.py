from project_mcp.plugins.astro.usages import rendered_tags


def test_tags_inside_comments_scripts_and_styles_are_not_rendered():
    template = (
        "<!-- <Old /> -->\n"
        "{/* <Gone /> */}\n"
        "<script>const html = '<Inline />';</script>\n"
        "<style>/* <Styled /> */</style>\n"
        "<Real />"
    )

    assert rendered_tags(template) == {"Real"}
