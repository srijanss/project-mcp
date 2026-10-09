import json
import posixpath
import re
from pathlib import Path, PurePosixPath

from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.astro import tree_usages
from project_mcp.plugins.astro.routes import route_for
from project_mcp.plugins.astro.usages import default_imports, named_imports, rendered_tags
from project_mcp.plugins.javascript.analyzer import JavaScriptAnalyzer
from project_mcp.plugins.react import tree_usages as react_tree_usages
from project_mcp.plugins.react.exports import default_export_name, export_aliases

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

    @property
    def warnings(self) -> list[str]:
        """The javascript parser's warnings, such as its regex fallback."""
        return self._javascript.warnings

    @property
    def backend(self) -> str:
        """The parser backend the frontmatter is analyzed with; it feeds the plugin fingerprint."""
        return self._javascript.backend

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
        route = route_for(path)
        if route:
            metadata = {"framework_kind": "astro_page", **route}
        elif PurePosixPath(path).parts[:2] == ("src", "layouts") or _SLOT.search(template):
            metadata = {"framework_kind": "astro_layout"}
        else:
            metadata = {"framework_kind": "astro_component"}
        name = Path(path).stem
        analysis.symbols.append(
            {
                "name": name,
                "qualified_name": f"{self.module_name(path)}.{name}",
                "kind": "component",
                "start_line": 1,
                "end_line": end_line,
                "visibility": "public",
                "metadata": metadata,
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
        self._tag_endpoints(context)
        self._link_renders(context)

    def _link_renders(self, context) -> None:
        """Link each .astro component to the .astro components its template renders,
        and to the components JS/TS files export as their default."""
        context.conn.execute(
            """
            DELETE FROM relationships
            WHERE relationship_type = 'renders' AND source_entity_type = 'symbol'
              AND source_entity_id IN (
                SELECT s.id FROM symbols s JOIN files f ON f.id = s.file_id
                WHERE f.project_id = ? AND f.path LIKE '%.astro'
              )
            """,
            (context.project_id,),
        )
        component_ids = dict(
            context.conn.execute(
                """
                SELECT f.path, s.id FROM symbols s JOIN files f ON f.id = s.file_id
                WHERE f.project_id = ? AND f.path LIKE '%.astro' AND s.kind = 'component'
                """,
                (context.project_id,),
            )
        )
        script_components: dict[str, list[tuple[int, str]]] = {}
        for path, symbol_id, name in context.conn.execute(
            """
            SELECT f.path, s.id, s.name FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE f.project_id = ? AND f.path NOT LIKE '%.astro' AND s.kind = 'component'
            ORDER BY s.start_line
            """,
            (context.project_id,),
        ):
            script_components.setdefault(path, []).append((symbol_id, name))
        defaults: dict[str, int | None] = {}
        aliases: dict[str, dict[str, str]] = {}
        for path, source_id in component_ids.items():
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            script, template = _split(source)
            imports = self._imports(script)
            targets = set()
            for tag in rendered_tags(template) & imports.keys():
                specifier, imported = imports[tag]
                for candidate in self.resolve_import(path, specifier):
                    if candidate in component_ids and imported == "default":
                        targets.add(component_ids[candidate])
                    elif candidate in script_components and imported != "default":
                        if candidate not in aliases:
                            aliases[candidate] = self._export_aliases(context, candidate)
                        name = aliases[candidate].get(imported, imported)
                        rows = script_components[candidate]
                        targets.add(next((id_ for id_, row_name in rows if row_name == name), None))
                    elif candidate in script_components:
                        if candidate not in defaults:
                            defaults[candidate] = self._default_component(
                                context, candidate, script_components[candidate]
                            )
                        targets.add(defaults[candidate])
            targets -= {source_id, None}
            for target_id in sorted(targets):
                context.conn.execute(
                    """
                    INSERT INTO relationships (
                        source_entity_type, source_entity_id,
                        target_entity_type, target_entity_id,
                        relationship_type, confidence
                    ) VALUES ('symbol', ?, 'symbol', ?, 'renders', 'high')
                    """,
                    (source_id, target_id),
                )

    def _imports(self, script: str) -> dict[str, tuple[str, str]]:
        """The (module specifier, imported name) behind each name a frontmatter
        script imports; a default import's imported name is "default"."""
        if self.backend == "tree-sitter":
            defaults, named = tree_usages.default_imports(script), tree_usages.named_imports(script)
        else:
            defaults, named = default_imports(script), named_imports(script)
        return {**{name: (specifier, "default") for name, specifier in defaults.items()}, **named}

    def _export_aliases(self, context, path: str) -> dict[str, str]:
        """The local name behind each export a JS/TS file renames, by exported name."""
        try:
            source = (Path(context.project_root) / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {}
        if self.backend == "tree-sitter":
            return react_tree_usages.export_aliases(source, react_tree_usages.grammar_for(path))
        return export_aliases(source)

    def _default_component(self, context, path: str, rows: list[tuple[int, str]]) -> int | None:
        """The component a JS/TS file exports as its default; when that can't be
        read, the file's only component."""
        try:
            source = (Path(context.project_root) / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if self.backend == "tree-sitter":
            name = react_tree_usages.default_export_name(source, react_tree_usages.grammar_for(path))
        else:
            name = default_export_name(source)
        if name is None:
            return rows[0][0] if len(rows) == 1 else None
        return next((symbol_id for symbol_id, component in rows if component == name), None)

    def _tag_endpoints(self, context) -> None:
        """Tag the module of each .ts/.js file under src/pages as an endpoint with its route."""
        for path, file_id in context.path_to_file_id.items():
            route = route_for(path)
            if route is None or path.endswith(".astro"):
                continue
            context.conn.execute(
                """
                UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'), '$.framework_kind', 'astro_endpoint',
                    '$.route', ?, '$.route_kind', ?
                )
                WHERE file_id = ? AND kind = 'module'
                """,
                (route["route"], route["route_kind"], file_id),
            )
