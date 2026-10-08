import json
import posixpath
import re
from pathlib import Path, PurePosixPath

from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.javascript.analyzer import JavaScriptAnalyzer

_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")
_FENCE = "---"
_SLOT = re.compile(r"<slot[\s/>]")
_EXTENSIONS = (".astro", ".ts", ".tsx", ".js", ".jsx")


def _split(source: str) -> tuple[str, str]:
    """The script between the leading `---` fences and the template after them.

    The script is padded with a blank line so its lines keep their numbers in
    the .astro file; without fences it is empty and the template is the file.
    """
    lines = source.splitlines()
    if lines and lines[0].strip() == _FENCE:
        for end, line in enumerate(lines[1:], start=1):
            if line.strip() == _FENCE:
                return "\n" + "\n".join(lines[1:end]), "\n".join(lines[end + 1 :])
    return "", source


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
        """Analyze the frontmatter as TypeScript; the whole file is the module
        and the component (or layout) it defines."""
        script, template = _split(source)
        analysis = self._javascript.analyze(str(Path(path).with_suffix(".ts")), script)
        end_line = len(source.splitlines()) or 1
        for symbol in analysis.symbols:
            if symbol["kind"] == "module":
                symbol["end_line"] = end_line
        is_layout = PurePosixPath(path).parts[:2] == ("src", "layouts") or _SLOT.search(template)
        name = Path(path).stem
        analysis.symbols.append(
            {
                "name": name,
                "qualified_name": f"{self.module_name(path)}.{name}",
                "kind": "component",
                "start_line": 1,
                "end_line": end_line,
                "visibility": "public",
                "metadata": {"framework_kind": "astro_layout" if is_layout else "astro_component"},
            }
        )
        return analysis

    def is_test_file(self, path: Path) -> bool:
        return self._javascript.is_test_file(path)

    def resolve_import(self, importer: str, module: str) -> list[str]:
        """Candidate files for a relative module specifier; bare packages resolve to none."""
        if not module.startswith("."):
            return []
        base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), module))
        if base.endswith(_EXTENSIONS):
            return [base]
        return [base + ext for ext in _EXTENSIONS] + [
            f"{base}/index{ext}" for ext in _EXTENSIONS
        ]

    def enrich(self, context) -> None:
        pass
