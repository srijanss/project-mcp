import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.tests import get_tests_for

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Button.jsx": "export function Button() {\n  return <button />;\n}\n",
    "src/Real.test.jsx": (
        "import { Button } from './Button';\n\n"
        "test('renders', () => {\n  render(<Button />);\n});\n"
    ),
    "src/Stub.test.jsx": (
        "import { Button } from './Button';\n\n"
        "test('stubs', () => {\n  const Button = () => null;\n  render(<Button />);\n});\n"
    ),
}


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_a_test_rebinding_an_imported_name_gets_no_render_evidence_for_the_import(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.Button.Button") == [
        {"test_file": "src/Real.test.jsx", "confidence": "high", "evidence": ["direct_import", "jsx_render"]},
        {"test_file": "src/Stub.test.jsx", "confidence": "high", "evidence": ["direct_import"]},
    ]
