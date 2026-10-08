import posixpath
from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.javascript.dependencies import list_npm_dependencies
from project_mcp.plugins.javascript.parser import (
    _module_qualified_name,
    extract_js_imports,
    parse_js_source,
)
from project_mcp.plugins.javascript.tree_parser import parse_js_tree

_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")
# file suffix -> the tree-sitter grammar that parses it
_GRAMMARS = {".js": "javascript", ".jsx": "tsx", ".ts": "typescript", ".tsx": "tsx"}


class JavaScriptAnalyzer:
    def __init__(self) -> None:
        problem = treesitter.missing("javascript") or treesitter.missing("typescript")
        self.backend = "regex" if problem else "tree-sitter"
        self.warnings = [f"falls back to its regex parser: {problem}"] if problem else []

    def module_name(self, path: str) -> str:
        """The qualified name of the module symbol this file is indexed as."""
        return _module_qualified_name(path)

    def list_dependencies(self, project_root: Path) -> list[dict]:
        """The dependencies this project's manifests declare for the ecosystem."""
        return list_npm_dependencies(Path(project_root))

    def is_test_file(self, path: Path) -> bool:
        path = Path(path)
        in_test_dir = bool({"tests", "__tests__"} & set(path.parts[:-1]))
        return in_test_dir or path.stem.endswith((".test", ".spec"))

    def analyze(self, path: str, source: str) -> FileAnalysis:
        if self.backend == "tree-sitter":
            symbols = parse_js_tree(path, source, _GRAMMARS[Path(path).suffix])
        else:
            symbols = parse_js_source(path, source)
        return FileAnalysis(
            symbols=symbols,
            imports=[
                imp["module"]
                for imp in extract_js_imports(path, source)
                if not imp.get("dynamic") and imp.get("module")
            ],
        )

    def resolve_import(self, importer: str, module: str) -> list[str]:
        """Candidate files for a relative module specifier; bare packages resolve to none."""
        if not module.startswith("."):
            return []
        base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), module))
        return [base + ext for ext in _EXTENSIONS] + [
            f"{base}/index{ext}" for ext in _EXTENSIONS
        ]
