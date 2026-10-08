from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Button.tsx": "export function Button() {\n  return <button />;\n}\n",
    "src/Card.tsx": "export default function Card() {\n  return <div />;\n}\n",
    "src/Icon.tsx": "export function Icon() {\n  return <i />;\n}\n",
    "src/Button.test.tsx": (
        "import { render } from '@testing-library/react';\n"
        "import { Button as Btn } from './Button';\n"
        "import Panel from './Card';\n"
        "import { Icon } from './Icon';\n\n"
        "test('renders', () => {\n"
        "  render(<Panel><Btn /></Panel>);\n"
        "  expect(Icon.name).toBe('Icon');\n"
        "});\n"
    ),
}


def _link(evidence):
    return [{"test_file": "src/Button.test.tsx", "confidence": "high", "evidence": evidence}]


def _scan(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn


def test_a_test_rendering_an_imported_component_adds_jsx_render_evidence(tmp_path):
    _scan(tmp_path)

    assert get_tests_for(tmp_path, "src.Button.Button") == _link(["direct_import", "jsx_render"])
    assert get_tests_for(tmp_path, "src.Card.Card") == _link(["direct_import", "jsx_render"])
    assert get_tests_for(tmp_path, "src.Icon.Icon") == _link(["direct_import"])


def test_jsx_render_evidence_survives_reindexing_the_component(tmp_path):
    conn = _scan(tmp_path)
    component = tmp_path / "src/Button.tsx"
    component.write_text(component.read_text() + "\nexport const SIZE = 2;\n")
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.Button.Button") == _link(["direct_import", "jsx_render"])


def test_removing_the_render_leaves_only_direct_import_evidence(tmp_path):
    conn = _scan(tmp_path)
    test_file = tmp_path / "src/Button.test.tsx"
    test_file.write_text(test_file.read_text().replace("<Btn />", ""))
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.Button.Button") == _link(["direct_import"])
    assert get_tests_for(tmp_path, "src.Card.Card") == _link(["direct_import", "jsx_render"])
