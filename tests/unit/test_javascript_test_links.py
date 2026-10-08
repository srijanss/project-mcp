import json

import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter

FILES = {
    "src/format.js": (
        "export function title(s) {\n  return s;\n}\n\n"
        "export function slug(s) {\n  return s;\n}\n\n"
        "function plain(s) {\n  return s;\n}\n\n"
        "export default plain;\n"
    ),
    "src/__tests__/format.js": (
        "import {\n  title as heading,\n  missing,\n} from '../format';\n"
        "import fmt from '../format';\n"
        "import { render } from 'testing-library';\n"
    ),
    "src/page.js": "import { slug } from './format';\n",
}


@pytest.mark.parametrize("backend", ["tree-sitter", "regex"])
def test_test_files_link_to_imported_symbols_on_either_backend(backend, tmp_path, monkeypatch):
    if backend == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    elif treesitter.missing("javascript") is not None:
        pytest.skip("tree-sitter is not installed")
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    links = conn.execute(
        """
        SELECT f.path, s.qualified_name, r.confidence, r.evidence_json
        FROM relationships r
        JOIN files f ON f.id = r.source_entity_id AND r.source_entity_type = 'file'
        JOIN symbols s ON s.id = r.target_entity_id AND r.target_entity_type = 'symbol'
        WHERE r.relationship_type = 'tests'
        ORDER BY 2
        """
    ).fetchall()
    assert [(path, name, confidence, json.loads(evidence)) for path, name, confidence, evidence in links] == [
        ("src/__tests__/format.js", "src.format.plain", "high", ["direct_import"]),
        ("src/__tests__/format.js", "src.format.title", "high", ["direct_import"]),
    ]
