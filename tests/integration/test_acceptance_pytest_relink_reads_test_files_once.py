from collections import Counter
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.python import linking


def test_relinking_tests_reads_each_test_file_once(tmp_path, monkeypatch):
    files = {
        "app/__init__.py": "",
        "app/shapes.py": "def volume(x):\n    return x ** 3\n",
        "tests/__init__.py": "",
        "tests/conftest.py": (
            "import pytest\nfrom app.shapes import volume\n\n\n@pytest.fixture\ndef cube():\n    return volume(2)\n"
        ),
        "tests/test_cube.py": "def test_cube(cube):\n    assert cube == 8\n",
    }
    for path, source in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(source)
    conn, config = get_connection(tmp_path), load_config(tmp_path)
    run_scan(conn, tmp_path, config)
    reads = Counter()
    original = linking._read_source

    def counting_read(path):
        reads[Path(path).relative_to(tmp_path).as_posix()] += 1
        return original(path)

    monkeypatch.setattr(linking, "_read_source", counting_read)
    (tmp_path / "app" / "shapes.py").write_text("def volume(x):\n    return x * x * x\n")

    refresh_index(conn, tmp_path, config)

    # Linking test evidence reads each test file once; conftest.py is read
    # once more to relink its calls into app/shapes.py, which it imports.
    assert reads == {"tests/__init__.py": 1, "tests/conftest.py": 2, "tests/test_cube.py": 1}
