from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "package.json": '{"devDependencies": {"vitest": "^1.0.0"}}',
    "src/math.ts": (
        "export function add(a, b) {\n  return a + b;\n}\n\n"
        "export function sub(a, b) {\n  return a - b;\n}\n\n"
        "export function div(a, b) {\n  return a / b;\n}\n\n"
        "export default function mul(a, b) {\n  return a * b;\n}\n"
    ),
    "src/app.ts": "import { div } from './math';\n\nexport function run() {\n  return div(4, 2);\n}\n",
    "src/math.test.ts": (
        "import { describe, it, expect } from 'vitest';\n"
        "import { add, sub as minus } from './math';\n"
        "import times from './math';\n\n"
        "describe('math', () => {\n"
        "  it('adds', () => expect(add(1, 2)).toBe(3));\n"
        "  it('subtracts', () => expect(minus(3, 2)).toBe(1));\n"
        "  it('multiplies', () => expect(times(2, 3)).toBe(6));\n"
        "});\n"
    ),
    "tests/smoke.test.ts": "import { it } from 'vitest';\n\nit('runs', () => {});\n",
}

DIRECT = [{"test_file": "src/math.test.ts", "confidence": "high", "evidence": ["direct_import"]}]


def _scan(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn


def _test_links_from(conn, path):
    return conn.execute(
        """
        SELECT COUNT(*) FROM relationships r JOIN files f ON f.id = r.source_entity_id
        WHERE r.relationship_type = 'tests' AND r.source_entity_type = 'file' AND f.path = ?
        """,
        (path,),
    ).fetchone()[0]


def test_a_js_test_file_tests_the_project_symbols_it_imports(tmp_path):
    _scan(tmp_path)

    assert get_tests_for(tmp_path, "src.math.add") == DIRECT
    assert get_tests_for(tmp_path, "src.math.sub") == DIRECT
    assert get_tests_for(tmp_path, "src.math.mul") == DIRECT
    assert get_tests_for(tmp_path, "src.math.div") == []


def test_a_test_file_without_project_imports_links_nothing(tmp_path):
    conn = _scan(tmp_path)

    assert _test_links_from(conn, "tests/smoke.test.ts") == 0


def test_refresh_drops_the_link_when_the_import_is_deleted(tmp_path):
    conn = _scan(tmp_path)
    test_file = tmp_path / "src/math.test.ts"
    test_file.write_text(test_file.read_text().replace("add, sub as minus", "add"))
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.math.add") == DIRECT
    assert get_tests_for(tmp_path, "src.math.sub") == []


def test_reindexing_the_tested_file_keeps_the_link(tmp_path):
    conn = _scan(tmp_path)
    source = tmp_path / "src/math.ts"
    source.write_text(source.read_text() + "\nexport const PI = 3.14;\n")
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "src.math.add") == DIRECT
