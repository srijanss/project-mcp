from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

SOURCE = """\
function helper() {
  return 1;
}

function run(items) {
  helper();
  items.forEach((item) => helper());
  const name = "helper";
  window[name]();
  undefinedElsewhere();
}

class Job {
  start() {
    this.step();
    helper();
  }

  step() {}
}
"""


def test_static_calls_between_functions_become_calls_relationships(tmp_path):
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
    assert sorted(calls) == [
        ("jobs.Job.start", "jobs.Job.step"),
        ("jobs.Job.start", "jobs.helper"),
        ("jobs.run", "jobs.helper"),
    ]
