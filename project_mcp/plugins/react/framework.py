"""React as a framework plugin on top of the javascript plugin."""
import json
import os
import re
from pathlib import Path

_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")
_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_SKIPPED_DIRS = {"node_modules", ".git"}
_REACT_IMPORT = re.compile(
    r"""^\s*import\s+(?:[^'";]*?\s+from\s+)?['"]react['"]"""
    r"""|\brequire\(\s*['"]react['"]\s*\)""",
    re.MULTILINE,
)


def _declares_react(root: Path) -> bool:
    try:
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, dict):
        return False
    return any(
        isinstance(manifest.get(section), dict) and "react" in manifest[section]
        for section in _DEPENDENCY_SECTIONS
    )


def _imports_react(root: Path) -> bool:
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in _SKIPPED_DIRS]
        for name in names:
            if not name.endswith(_EXTENSIONS):
                continue
            try:
                source = (Path(directory) / name).read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            if _REACT_IMPORT.search(source):
                return True
    return False


class ReactFramework:
    def detect(self, context) -> bool:
        """True when package.json declares `react` or a JS/TS file imports it."""
        root = context.project_root
        return _declares_react(root) or _imports_react(root)

    def enrich(self, context) -> None:
        self._tag_components(context)

    def _tag_components(self, context) -> None:
        """Tag the components the javascript plugin found in .js/.ts files as react components."""
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            context.conn.execute(
                """
                UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'), '$.framework_kind', 'react_component'
                )
                WHERE file_id = ? AND kind = 'component'
                """,
                (file_id,),
            )
