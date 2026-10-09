from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.tests import get_tests_for

FILES = {
    "app.py": "def target():\n    return 1\n",
    "tests/test_app.py": (
        "from unittest import mock\n"
        "from app import target\n\n"
        "def helper():\n    return target()\n\n"
        "def test_both():\n"
        "    with mock.patch('tests.test_app.helper'):\n"
        "        assert target() == 1\n"
        "        helper()\n"
    ),
}


def test_a_test_calling_the_symbol_directly_is_not_also_set_aside_for_patching_a_helper(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert get_tests_for(tmp_path, "app.target") == [
        {
            "test_file": "tests/test_app.py",
            "confidence": "high",
            "evidence": ["symbol_reference"],
            "tests": ["tests.test_app.test_both"],
        }
    ]
