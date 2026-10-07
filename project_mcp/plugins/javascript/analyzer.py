import posixpath
from pathlib import Path

from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.javascript.parser import extract_js_imports, parse_js_source

_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")


class JavaScriptAnalyzer:
    def is_test_file(self, path: Path) -> bool:
        path = Path(path)
        in_test_dir = bool({"tests", "__tests__"} & set(path.parts[:-1]))
        return in_test_dir or path.stem.endswith((".test", ".spec"))

    def analyze(self, path: str, source: str) -> FileAnalysis:
        return FileAnalysis(
            symbols=parse_js_source(path, source),
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
