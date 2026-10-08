import pytest

from project_mcp.plugins.react.pages import is_page_path


@pytest.mark.parametrize(
    "path",
    [
        "pages/index.tsx",
        "pages/blog/[slug].jsx",
        "src/pages/about.js",
        "app/page.tsx",
        "app/dashboard/page.tsx",
        "src/app/settings/profile/page.jsx",
    ],
)
def test_files_in_page_locations_are_pages(path):
    assert is_page_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/components/Button.tsx",
        "src/components/page.tsx",
        "src/homepages/Banner.tsx",
        "app/dashboard/layout.tsx",
        "app/dashboard/Widget.tsx",
        "pages/styles.css",
        "pages_old/index.tsx",
    ],
)
def test_files_elsewhere_are_not_pages(path):
    assert not is_page_path(path)
