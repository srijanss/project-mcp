import asyncio
import json

from project_mcp.db import get_connection
from project_mcp.main_stdio import build_server

LIB = """\
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    use super::*;

    fn two() -> i32 {
        2
    }

    #[test]
    fn adds_two_numbers() {
        assert_eq!(add(two(), 2), 4);
    }

    #[tokio::test]
    async fn adds_asynchronously() {
        assert_eq!(add(1, 1), 2);
    }
}
"""

INTEGRATION = """\
use sample::add;

fn setup() {}

#[test]
fn adds_from_outside_the_crate() {
    setup();
    assert_eq!(add(2, 3), 5);
}

#[tokio::test(flavor = "multi_thread")]
async fn adds_on_a_multi_thread_runtime() {
    assert_eq!(add(0, 0), 0);
}
"""


def _project(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "sample"\nversion = "0.1.0"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "integration.rs").write_text(INTEGRATION)
    return tmp_path


def test_rust_test_functions_are_recorded_as_tests_and_counted(tmp_path):
    project = _project(tmp_path)
    server = build_server(project)

    summary = json.loads(asyncio.run(server.call_tool("get_test_summary", {})).content[0].text)

    assert summary["total_tests"] == 4
    conn = get_connection(project)
    recorded = conn.execute(
        """
        SELECT s.qualified_name, t.framework FROM tests t
        JOIN symbols s ON s.id = t.symbol_id
        ORDER BY s.qualified_name
        """
    ).fetchall()
    conn.close()
    assert [name for name, _ in recorded] == [
        "src.lib.tests.adds_asynchronously",
        "src.lib.tests.adds_two_numbers",
        "tests.integration.adds_from_outside_the_crate",
        "tests.integration.adds_on_a_multi_thread_runtime",
    ]
    assert {framework for _, framework in recorded} == {"cargo"}
