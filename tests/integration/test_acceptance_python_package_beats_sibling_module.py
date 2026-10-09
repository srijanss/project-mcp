from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependencies

FILES = {
    "pkg.py": "X = 0\n",
    "pkg/__init__.py": "X = 1\n",
    "pkg/sub.py": "Y = 0\n",
    "pkg/sub/__init__.py": "Y = 2\n",
    "plain.py": "import pkg\n",
    "nested.py": "import pkg.sub\n",
}


def _imports(root, module):
    return sorted(d["target"] for d in get_dependencies(root, module) if d["relationship_type"] == "imports")


def test_a_package_wins_over_a_module_of_the_same_name_as_python_resolves_it(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert _imports(tmp_path, "plain") == ["pkg/__init__.py"]
    assert _imports(tmp_path, "nested") == ["pkg/sub/__init__.py"]
