from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "app.py": (
        "def t():\n    return 1\n\n\n"
        "def a():\n    return t()\n\n\n"
        "def b():\n    return t()\n\n\n"
        "def c():\n    return a() + b()\n"
    ),
    "tests/test_c.py": (
        "from unittest import mock\n"
        "from app import c\n\n\n"
        "@mock.patch('app.a')\n"
        "def test_c(m):\n    m.return_value = 1\n    c()\n"
    ),
}


def test_a_test_mocking_one_branch_of_a_diamond_still_covers_the_symbol_through_the_other(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "app.t") == [
        {
            "test_file": "tests/test_c.py",
            "confidence": "medium",
            "evidence": ["indirect_call"],
            "via": ["app.c", "app.b"],
            "tests": ["tests.test_c.test_c"],
        }
    ]
