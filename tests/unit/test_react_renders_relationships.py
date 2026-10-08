from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
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
