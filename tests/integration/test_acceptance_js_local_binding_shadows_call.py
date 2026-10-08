from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

SOURCE = """\
function helper() {}

function byParameter(helper) {
  helper();
}

function byDestructuredParameter({ helper }, [other = helper]) {
  helper();
}

function byLocal() {
  const helper = makeHelper();
  helper();
}

function byCatch() {
  try {} catch (helper) {
    helper();
  }
}

const byArrowParameter = (helper) => helper();

function linked() {
  helper();
}
"""


def test_calls_through_local_bindings_shadowing_a_module_function_are_not_linked(tmp_path):
    (tmp_path / "jobs.js").write_text(SOURCE)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    calls = conn.execute(
        """
        SELECT source.qualified_name, target.qualified_name
        FROM relationships
        JOIN symbols source ON source.id = relationships.source_entity_id
        JOIN symbols target ON target.id = relationships.target_entity_id
        WHERE relationship_type = 'calls'
        """
    ).fetchall()
    assert calls == [("jobs.linked", "jobs.helper")]
