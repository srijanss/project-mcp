import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.plugins.astro import framework, tree_usages


def _renders(tmp_path) -> int:
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}')
    (tmp_path / "src/components").mkdir(parents=True)
    (tmp_path / "src/pages").mkdir()
    (tmp_path / "src/components/Card.astro").write_text("---\n---\n<div />\n")
    (tmp_path / "src/pages/index.astro").write_text(
        "---\nimport Card from '../components/Card.astro';\n---\n<Card />\n"
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    return conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE relationship_type = 'renders'"
    ).fetchone()[0]


def test_without_tree_sitter_the_regex_parser_reads_the_frontmatter_imports(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off")

    def tree_parser_used(script):
        raise AssertionError("the frontmatter was read with the tree parser")

    monkeypatch.setattr(tree_usages, "default_imports", tree_parser_used)

    assert _renders(tmp_path) == 1


@pytest.mark.skipif(
    treesitter.missing("typescript") is not None, reason="tree-sitter is not installed"
)
def test_with_tree_sitter_available_the_syntax_tree_reads_the_frontmatter_imports(
    tmp_path, monkeypatch
):
    def regex_parser_used(script):
        raise AssertionError("the frontmatter was read with the regex parser")

    monkeypatch.setattr(framework, "default_imports", regex_parser_used)

    assert _renders(tmp_path) == 1
