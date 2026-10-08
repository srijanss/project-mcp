"""The default imports of a frontmatter script, read from a tree-sitter syntax tree."""
from project_mcp.plugins import treesitter


def default_imports(script: str) -> dict[str, str]:
    """The module specifier behind each default-imported name in a frontmatter script.

    The same result as `usages.default_imports`, read from the syntax tree; the
    script is TypeScript.
    """
    imports: dict[str, str] = {}
    for statement in treesitter.parse(script, "typescript").children:
        clause = next((c for c in statement.children if c.type == "import_clause"), None)
        if statement.type != "import_statement" or clause is None:
            continue
        if statement.text.startswith("import type "):
            continue
        default = next((c for c in clause.children if c.type == "identifier"), None)
        if default is not None:
            imports[default.text] = statement.field("source").text[1:-1]
    return imports
