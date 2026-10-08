import json
from pathlib import Path

from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.javascript.analyzer import JavaScriptAnalyzer

_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")
_FENCE = "---"


def _frontmatter(source: str) -> str:
    """The script between the leading `---` fences, padded with blank lines
    so its lines keep their numbers in the .astro file; empty without fences."""
    lines = source.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return ""
    for end, line in enumerate(lines[1:], start=1):
        if line.strip() == _FENCE:
            return "\n" + "\n".join(lines[1:end])
    return ""


class AstroFramework:
    def __init__(self) -> None:
        self._javascript = JavaScriptAnalyzer()

    def detect(self, context) -> bool:
        """True when package.json declares `astro` or an astro.config.* file exists."""
        root = context.project_root
        if any(root.glob("astro.config.*")):
            return True
        try:
            manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(manifest, dict):
            return False
        return any(
            isinstance(manifest.get(section), dict) and "astro" in manifest[section]
            for section in _DEPENDENCY_SECTIONS
        )

    def module_name(self, path: str) -> str:
        """The qualified name of the module symbol this file is indexed as."""
        return self._javascript.module_name(path)

    def analyze(self, path: str, source: str) -> FileAnalysis:
        """Analyze the frontmatter as TypeScript; the whole file is the module."""
        analysis = self._javascript.analyze(str(Path(path).with_suffix(".ts")), _frontmatter(source))
        for symbol in analysis.symbols:
            if symbol["kind"] == "module":
                symbol["end_line"] = len(source.splitlines()) or 1
        return analysis

    def is_test_file(self, path: Path) -> bool:
        return self._javascript.is_test_file(path)

    def resolve_import(self, importer: str, module: str) -> list[str]:
        """Candidate files for a relative module specifier; bare packages resolve to none."""
        return self._javascript.resolve_import(importer, module)

    def enrich(self, context) -> None:
        pass
