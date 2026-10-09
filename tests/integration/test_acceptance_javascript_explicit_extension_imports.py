from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/math.js": "export function add() {\n  return 1;\n}\n",
    "src/check.test.js": "import { add } from './math.js';\n\ntest('adds', () => add());\n",
}


def test_a_test_importing_a_file_by_its_full_name_is_linked_to_the_imported_symbol(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.math.add") == [
        {"test_file": "src/check.test.js", "confidence": "high", "evidence": ["direct_import"]}
    ]
