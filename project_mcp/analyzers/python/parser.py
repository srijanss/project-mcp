import ast
from pathlib import Path


def _module_qualified_name(path: str) -> str:
    module_path = Path(path).with_suffix("")
    return ".".join(module_path.parts)


def _visibility(name: str) -> str:
    return "private" if name.startswith("_") else "public"


def _base_repr(node: ast.expr):
    if isinstance(node, (ast.Name, ast.Attribute)):
        return ast.unparse(node)
    return {"dynamic": True, "expression": ast.unparse(node)}


def parse_python_source(path: str, source: str) -> list[dict]:
    module_name = _module_qualified_name(path)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [{"kind": "parse_error", "path": path, "error": str(exc)}]

    symbols = [
        {
            "name": module_name,
            "qualified_name": module_name,
            "kind": "module",
            "start_line": 1,
            "end_line": getattr(tree, "end_lineno", None),
            "visibility": "public",
        }
    ]

    def visit_body(body, qualified_prefix, in_class):
        for node in body:
            if isinstance(node, ast.ClassDef):
                qualified_name = f"{qualified_prefix}.{node.name}"
                symbols.append(
                    {
                        "name": node.name,
                        "qualified_name": qualified_name,
                        "kind": "class",
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "visibility": _visibility(node.name),
                        "bases": [_base_repr(base) for base in node.bases],
                    }
                )
                visit_body(node.body, qualified_name, in_class=True)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified_name = f"{qualified_prefix}.{node.name}"
                symbols.append(
                    {
                        "name": node.name,
                        "qualified_name": qualified_name,
                        "kind": "method" if in_class else "function",
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "visibility": _visibility(node.name),
                    }
                )

    visit_body(tree.body, module_name, in_class=False)
    return symbols


def extract_imports(path: str, source: str) -> list[dict]:
    tree = ast.parse(source, filename=path)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {
                        "module": alias.name,
                        "names": [],
                        "level": 0,
                        "line": node.lineno,
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            record = {
                "module": node.module,
                "names": [] if names == ["*"] else names,
                "level": node.level,
                "line": node.lineno,
            }
            if names == ["*"]:
                record["dynamic"] = True
            imports.append(record)

    return imports
