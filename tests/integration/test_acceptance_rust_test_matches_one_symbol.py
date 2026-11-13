import asyncio
import json

from project_mcp.db import get_connection
from project_mcp.main_stdio import build_server

LIB = """\
#[cfg(test)]
mod tests {
    struct Fixture;

    impl Fixture {
        fn adds(&self) {}
    }

    #[test]
    fn adds() {
        Fixture.adds();
    }
}
"""


def test_a_test_sharing_its_name_with_a_method_is_recorded_once_against_the_test(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)
    server = build_server(tmp_path)

    summary = json.loads(asyncio.run(server.call_tool("get_test_summary", {})).content[0].text)

    assert summary["total_tests"] == 1
    conn = get_connection(tmp_path)
    recorded = conn.execute(
        "SELECT s.qualified_name, s.start_line FROM tests t JOIN symbols s ON s.id = t.symbol_id"
    ).fetchall()
    conn.close()
    assert recorded == [("src.lib.tests.adds", 10)]
