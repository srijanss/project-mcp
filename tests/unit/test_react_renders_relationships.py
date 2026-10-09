import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins import treesitter
from project_mcp.plugins.registry import builtin_registry
from tests.golden import touch_indexed_files

REACT = '{"dependencies": {"react": "^18.0.0"}}'


def _scan(tmp_path, files):
    (tmp_path / "package.json").write_text(REACT)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    return conn


def _renders(conn):
    return sorted(
        conn.execute(
            """
            SELECT src.qualified_name, dst.qualified_name, r.confidence
            FROM relationships r
            JOIN symbols src ON src.id = r.source_entity_id
            JOIN symbols dst ON dst.id = r.target_entity_id
            WHERE r.relationship_type = 'renders'
            """
        ).fetchall()
    )


def test_default_imports_link_to_the_default_component_whatever_the_local_name(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/Card/index.tsx": "export default function Card() {\n  return <div />;\n}\n",
            "src/App.tsx": (
                "import Panel from './Card';\n\n"
                "export function App() {\n  return <Panel />;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [("src.App.App", "src.Card.index.Card", "high")]


def test_aliased_named_imports_link_to_the_component_by_its_exported_name(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/ui.tsx": (
                "export function Button() {\n  return <button />;\n}\n\n"
                "export function Link() {\n  return <a />;\n}\n"
            ),
            "src/App.tsx": (
                "import { Button as Btn } from './ui';\n\n"
                "export function App() {\n  return <Btn />;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [("src.App.App", "src.ui.Button", "high")]


def test_each_usage_is_linked_from_the_component_that_contains_it(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/Item.tsx": "export function Item() {\n  return <li />;\n}\n",
            "src/Lists.tsx": (
                "import { Item } from './Item';\n\n"
                "export function Empty() {\n  return null;\n}\n\n"
                "export function Full() {\n  return <Item />;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [("src.Lists.Full", "src.Item.Item", "high")]


def test_a_refresh_does_not_duplicate_renders_relationships(tmp_path):
    files = {
        "src/Item.tsx": "export function Item() {\n  return <li />;\n}\n",
        "src/App.tsx": (
            "import { Item } from './Item';\n\n"
            "export function App() {\n  return <Item />;\n}\n"
        ),
    }
    conn = _scan(tmp_path, files)
    touch_indexed_files(conn, tmp_path)

    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert _renders(conn) == [("src.App.App", "src.Item.Item", "high")]


def test_a_named_import_that_is_not_a_component_is_not_linked_to_the_files_only_component(
    tmp_path,
):
    conn = _scan(
        tmp_path,
        {
            "src/Panel.tsx": (
                "export const Theme = 'dark';\n\n"
                "export function Panel() {\n  return <div />;\n}\n"
            ),
            "src/App.tsx": (
                "import { Theme } from './Panel';\n\n"
                "export function App() {\n  return <Theme />;\n}\n"
            ),
        },
    )

    assert _renders(conn) == []


def test_a_default_import_links_to_the_exported_default_even_when_its_name_matches_another_component(
    tmp_path,
):
    conn = _scan(
        tmp_path,
        {
            "src/ui.tsx": (
                "export function Helper() {\n  return <i />;\n}\n\n"
                "export default function Main() {\n  return <main />;\n}\n"
            ),
            "src/App.tsx": (
                "import Helper from './ui';\nimport Panel from './ui';\n\n"
                "export function App() {\n  return <><Helper /><Panel /></>;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [("src.App.App", "src.ui.Main", "high")]


def test_a_default_import_of_a_non_component_does_not_fall_back_to_another_component(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/store.tsx": (
                "export const store = {};\n\n"
                "export function Provider() {\n  return <div />;\n}\n\n"
                "export default store;\n"
            ),
            "src/App.tsx": (
                "import Store from './store';\n\n"
                "export function App() {\n  return <Store />;\n}\n"
            ),
        },
    )

    assert _renders(conn) == []


def test_a_default_import_follows_a_wrapper_export_written_over_several_lines(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/badge.tsx": (
                "function Badge() {\n  return <b />;\n}\n\n"
                "function Pill() {\n  return <i />;\n}\n\n"
                "export default memo(\n  Badge,\n  areEqual,\n);\n"
            ),
            "src/App.tsx": (
                "import Tag from './badge';\n\n"
                "export function App() {\n  return <Tag />;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [("src.App.App", "src.badge.Badge", "high")]


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_a_tag_naming_a_same_file_component_links_to_it_unless_a_local_binding_shadows_it(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/other.tsx": "export function Badge() {\n  return <b />;\n}\n",
            "src/list.tsx": (
                "function Row() {\n  return <li />;\n}\n\n"
                "export function List({ Row }) {\n  return <ul><Row /><Badge /></ul>;\n}\n\n"
                "export function Table() {\n  return <table><Row /></table>;\n}\n\n"
                "const preview = <Row />;\n"
            ),
        },
    )

    assert _renders(conn) == [("src.list.Table", "src.list.Row", "high")]


def test_the_regex_backend_links_a_possibly_shadowed_tag_with_low_confidence_and_marks_its_user_partial(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off")
    conn = _scan(
        tmp_path,
        {
            "src/list.tsx": (
                "function Row() {\n  return <li />;\n}\n\n"
                "export function List({ Row }) {\n  return <ul><Row /></ul>;\n}\n\n"
                "export function Table() {\n  return <table><Row /></table>;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [
        ("src.list.List", "src.list.Row", "low"),
        ("src.list.Table", "src.list.Row", "high"),
    ]
    partial = conn.execute(
        "SELECT name FROM symbols WHERE json_extract(metadata_json, '$.partial')"
    ).fetchall()
    assert partial == [("List",)]


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_each_component_links_to_the_nested_component_it_declares_itself(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/Lists.tsx": (
                "export function A() {\n  const Item = () => <i />;\n  return <Item />;\n}\n\n"
                "export function B() {\n  const Item = () => <b />;\n  return <Item />;\n}\n"
            )
        },
    )

    assert _renders(conn) == [
        ("src.Lists.A", "src.Lists.A.Item", "high"),
        ("src.Lists.B", "src.Lists.B.Item", "high"),
    ]


@pytest.mark.parametrize("backend", ["tree-sitter", "regex"])
def test_a_named_import_links_to_the_component_behind_a_renamed_export(
    backend, tmp_path, monkeypatch
):
    if backend == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    elif treesitter.missing("tsx") is not None:
        pytest.skip("tree-sitter is not installed")
    conn = _scan(
        tmp_path,
        {
            "src/ui.tsx": (
                "function Button() {\n  return <button />;\n}\n\n"
                "function Link() {\n  return <a />;\n}\n\n"
                "export { Button as Primary, Link };\n"
            ),
            "src/App.tsx": (
                "import { Primary, Link as Anchor } from './ui';\n\n"
                "export function App() {\n  return <><Primary /><Anchor /></>;\n}\n"
            ),
        },
    )

    assert _renders(conn) == [
        ("src.App.App", "src.ui.Button", "high"),
        ("src.App.App", "src.ui.Link", "high"),
    ]
