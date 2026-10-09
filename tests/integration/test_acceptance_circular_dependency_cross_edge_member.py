from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.legacy import get_legacy_signals

FILES = {
    "b.py": "import a\nimport c\n",
    "a.py": "import b\n",
    "c.py": "import a\n",
}


def test_a_module_reaching_a_cycle_and_returned_to_through_it_is_flagged_too(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    flagged = {
        path
        for path in FILES
        if any(s["signal"] == "circular_dependency" for s in get_legacy_signals(tmp_path, path))
    }

    assert flagged == {"a.py", "b.py", "c.py"}
