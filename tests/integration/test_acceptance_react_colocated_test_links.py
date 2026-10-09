from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Button.tsx": "export function Button() {\n  return <button />;\n}\n",
    "src/Button.test.tsx": "test('clicks', () => {\n  expect(1).toBe(1);\n});\n",
    "src/Card.tsx": "export default function Card() {\n  return <div />;\n}\n",
    "src/__tests__/Card.spec.tsx": "test('shows', () => {});\n",
    "src/useToggle.ts": "export function useToggle() {\n  return [false, () => {}];\n}\n",
    "src/useToggle.test.ts": "test('toggles', () => {});\n",
    "src/Other.tsx": "export function Other() {\n  return <i />;\n}\n",
    "src/Icon.tsx": "export function Icon() {\n  return <i />;\n}\n",
    "src/Icon.test.tsx": "import { Icon } from './Icon';\n\ntest('icon', () => Icon);\n",
}


def _by_name(test_file):
    return [{"test_file": test_file, "confidence": "low", "evidence": ["naming_convention"]}]


def _scan(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn


def test_a_component_is_linked_to_its_colocated_test_by_basename(tmp_path):
    _scan(tmp_path)

    assert get_tests_for(tmp_path, "src.Button.Button") == _by_name("src/Button.test.tsx")
    assert get_tests_for(tmp_path, "src.Card.Card") == _by_name("src/__tests__/Card.spec.tsx")
    assert get_tests_for(tmp_path, "src.Other.Other") == []


def test_a_colocated_test_without_a_matching_component_is_linked_to_the_file(tmp_path):
    _scan(tmp_path)

    assert get_tests_for(tmp_path, "src.useToggle") == _by_name("src/useToggle.test.ts")


def test_a_direct_import_keeps_its_stronger_evidence(tmp_path):
    _scan(tmp_path)

    assert get_tests_for(tmp_path, "src.Icon.Icon") == [
        {"test_file": "src/Icon.test.tsx", "confidence": "high", "evidence": ["direct_import"]}
    ]


def test_deleting_the_colocated_test_removes_the_link(tmp_path):
    conn = _scan(tmp_path)
    (tmp_path / "src/Button.test.tsx").unlink()
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.Button.Button") == []
