from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

SOURCE = """\
function helper() {}

export default memo(function Badge() {
  const inner = () => 1;
  helper();
  inner();
});
"""


def test_calls_inside_a_wrapped_default_function_are_made_by_that_function(tmp_path):
    (tmp_path / "badge.js").write_text(SOURCE)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    calls = conn.execute(
        """
        SELECT source.qualified_name, target.qualified_name
        FROM relationships
        JOIN symbols source ON source.id = relationships.source_entity_id
        JOIN symbols target ON target.id = relationships.target_entity_id
        WHERE relationship_type = 'calls'
        ORDER BY 1, 2
        """
    ).fetchall()
    assert calls == [("badge.Badge", "badge.Badge.inner"), ("badge.Badge", "badge.helper")]
