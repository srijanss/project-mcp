"""React as a framework plugin on top of the javascript plugin."""
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from project_mcp.plugins import treesitter
from project_mcp.plugins.react import tree_usages, usages
from project_mcp.plugins.react.colocated import colocated_source
from project_mcp.plugins.react.dynamic import computed_components, dynamic_route_lines, lazy_imports
from project_mcp.plugins.react.exports import default_export_name, export_aliases
from project_mcp.plugins.react.pages import is_page_path
from project_mcp.plugins.react.routes import route_declarations
from project_mcp.plugins.react.scope import visible_component
from project_mcp.plugins.react.usages import import_candidates

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


class _Exports(NamedTuple):
    """How a file names its exports: the default's local name and the renamed ones."""

    default: str | None
    aliases: dict[str, str]


def _component_in(
    rows: list[tuple[int, str, int, int]], imported: str, exports: _Exports
) -> int | None:
    """The component a file's `imported` export refers to.

    A default import means the file's default export; when that can't be
    read, the file's only component. A renamed export means the component
    declared under its local name.
    """
    if imported == "default":
        if exports.default is None:
            return rows[0][0] if len(rows) == 1 else None
        imported = exports.default
    else:
        imported = exports.aliases.get(imported, imported)
    return next((id_ for id_, component, _, _ in rows if component == imported), None)


def _load_components(context) -> dict[str, list[tuple[int, str, int, int]]]:
    """The (id, name, start line, end line) of each component, by the .js/.ts file defining it.

    The regex parser records no end line; a component then runs to the next one.
    """
    components: dict[str, list[tuple[int, str, int, int]]] = {}
    for symbol_id, path, name, start, end in context.conn.execute(
        """
        SELECT s.id, f.path, s.name, s.start_line, s.end_line
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.kind = 'component'
        ORDER BY s.start_line
        """,
        (context.project_id,),
    ):
        if path.endswith(_EXTENSIONS):
            components.setdefault(path, []).append((symbol_id, name, start, end))
    for path, rows in components.items():
        ends = [start - 1 for _, _, start, _ in rows[1:]] + [float("inf")]
        components[path] = [
            (id_, name, start, end if end is not None else next_end)
            for (id_, name, start, end), next_end in zip(rows, ends)
        ]
    return components


def _insert_relationship(
    context, relationship_type: str, source: int, target: int, confidence: str = "high"
) -> None:
    context.conn.execute(
        """
        INSERT INTO relationships (
            source_entity_type, source_entity_id,
            target_entity_type, target_entity_id,
            relationship_type, confidence
        ) VALUES ('symbol', ?, 'symbol', ?, ?, ?)
        """,
        (source, target, relationship_type, confidence),
    )


def _resolve_component(components, defaults, importer: str, imports, tag: str) -> int | None:
    """The project component an imported JSX tag refers to, if any."""
    if tag not in imports:
        return None
    specifier, imported = imports[tag]
    target_path = next(
        (c for c in import_candidates(importer, specifier) if c in components), None
    )
    if target_path is None:
        return None
    return _component_in(components[target_path], imported, defaults[target_path])


def _declarer(context, file_id: int, rows, line: int) -> int | None:
    """The component enclosing `line`, else the file's module symbol."""
    enclosing = next((id_ for id_, _, start, end in rows if start <= line <= end), None)
    if enclosing is not None:
        return enclosing
    row = context.conn.execute(
        "SELECT id FROM symbols WHERE file_id = ? AND kind = 'module'", (file_id,)
    ).fetchone()
    return row[0] if row else None


def _mark_partial(context, symbol_ids) -> None:
    for symbol_id in symbol_ids:
        context.conn.execute(
            "UPDATE symbols SET metadata_json = json_set(COALESCE(metadata_json, '{}'),"
            " '$.partial', json('true')) WHERE id = ?",
            (symbol_id,),
        )


class ReactFramework:
    def __init__(self) -> None:
        problem = (
            treesitter.missing("javascript")
            or treesitter.missing("typescript")
            or treesitter.missing("tsx")
        )
        self.backend = "regex" if problem else "tree-sitter"
        self.warnings = [f"falls back to its regex parser: {problem}"] if problem else []

    def _imported_names(self, path: str, source: str) -> dict[str, tuple[str, str]]:
        if self.backend == "tree-sitter":
            return tree_usages.imported_names(source, tree_usages.grammar_for(path))
        return usages.imported_names(source)

    def _jsx_tags(self, path: str, source: str) -> list[tuple[str, int]]:
        if self.backend == "tree-sitter":
            return tree_usages.jsx_tags(source, tree_usages.grammar_for(path))
        return usages.jsx_tags(source)

    def _shadowed_tags(
        self, path: str, source: str, functions: bool = False
    ) -> set[tuple[str, int]]:
        if self.backend == "tree-sitter":
            return tree_usages.shadowed_tags(source, tree_usages.grammar_for(path), functions)
        return set()

    def _default_export_name(self, path: str, source: str) -> str | None:
        if self.backend == "tree-sitter":
            return tree_usages.default_export_name(source, tree_usages.grammar_for(path))
        return default_export_name(source)

    def _export_aliases(self, path: str, source: str) -> dict[str, str]:
        if self.backend == "tree-sitter":
            return tree_usages.export_aliases(source, tree_usages.grammar_for(path))
        return export_aliases(source)

    def _default_exports(self, context, components) -> dict[str, _Exports]:
        """How each file that defines components names its exports."""
        defaults: dict[str, _Exports] = {}
        for path in components:
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                source = ""
            defaults[path] = _Exports(
                self._default_export_name(path, source), self._export_aliases(path, source)
            )
        return defaults

    def detect(self, context) -> bool:
        """True when package.json declares `react` or a JS/TS file imports it."""
        root = context.project_root
        return _declares_react(root) or _imports_react(root)

    def enrich(self, context) -> None:
        self._tag_components(context)
        self._link_renders(context)
        self._declare_routes(context)
        self._link_dynamic(context)
        self._mark_rendered_tests(context)
        self._link_colocated_tests(context)

    def _link_colocated_tests(self, context) -> None:
        """Link each colocated test file to the component named like its source file,
        else to that file, unless it already tests that target by a stronger link."""
        context.conn.execute(
            "DELETE FROM relationships WHERE relationship_type = 'tests'"
            " AND source_entity_type = 'file' AND evidence_json = ?"
            " AND source_entity_id IN (SELECT id FROM files WHERE project_id = ?)",
            (json.dumps(["naming_convention"]), context.project_id),
        )
        paths = {path for path in context.path_to_file_id if path.endswith(_EXTENSIONS)}
        for test_path in sorted(paths):
            source_path = colocated_source(test_path, paths)
            if source_path is None:
                continue
            test_id, source_id = context.path_to_file_id[test_path], context.path_to_file_id[source_path]
            component = context.conn.execute(
                "SELECT id FROM symbols WHERE file_id = ? AND kind = 'component' AND name = ?",
                (source_id, PurePosixPath(source_path).stem),
            ).fetchone()
            target_type, target_id = ("symbol", component[0]) if component else ("file", source_id)
            linked = context.conn.execute(
                "SELECT 1 FROM relationships WHERE relationship_type = 'tests'"
                " AND source_entity_type = 'file' AND source_entity_id = ?"
                " AND target_entity_type = ? AND target_entity_id = ?",
                (test_id, target_type, target_id),
            ).fetchone()
            if linked:
                continue
            context.conn.execute(
                """
                INSERT INTO relationships (
                    source_entity_type, source_entity_id,
                    target_entity_type, target_entity_id,
                    relationship_type, confidence, evidence_json
                ) VALUES ('file', ?, ?, ?, 'tests', 'low', ?)
                """,
                (test_id, target_type, target_id, json.dumps(["naming_convention"])),
            )

    def _mark_rendered_tests(self, context) -> None:
        """Add jsx_render evidence to a test file's tests link to each component it renders."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        links: dict[str, list[tuple[int, int, list[str]]]] = {}
        for relationship_id, path, target, evidence_json in context.conn.execute(
            """
            SELECT r.id, f.path, r.target_entity_id, r.evidence_json
            FROM relationships r JOIN files f ON f.id = r.source_entity_id
            WHERE f.project_id = ? AND r.relationship_type = 'tests'
              AND r.source_entity_type = 'file' AND r.target_entity_type = 'symbol'
            """,
            (context.project_id,),
        ).fetchall():
            if path.endswith(_EXTENSIONS):
                evidence = json.loads(evidence_json) if evidence_json else []
                links.setdefault(path, []).append((relationship_id, target, evidence))
        for path, rows in links.items():
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            imports = self._imported_names(path, source)
            shadowed = self._shadowed_tags(path, source, functions=True)
            rendered = {
                _resolve_component(components, defaults, path, imports, tag)
                for tag, line in self._jsx_tags(path, source)
                if (tag, line) not in shadowed
            }
            for relationship_id, target, evidence in rows:
                updated = [e for e in evidence if e != "jsx_render"]
                if target in rendered:
                    updated.append("jsx_render")
                if updated != evidence:
                    context.conn.execute(
                        "UPDATE relationships SET evidence_json = ? WHERE id = ?",
                        (json.dumps(updated), relationship_id),
                    )

    def _link_dynamic(self, context) -> None:
        """Record lazy and computed components with low confidence, marking their users partial."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        partial: set[int] = set()
        links: set[tuple[int, int]] = set()
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rows = components.get(path, [])
            imports = self._imported_names(path, source)
            lazy = {name: (module, "default") for name, module in lazy_imports(source).items()}
            computed = computed_components(source)
            for tag, line in self._jsx_tags(path, source):
                user = _declarer(context, file_id, rows, line)
                if user is None or (tag not in lazy and tag not in computed):
                    continue
                partial.add(user)
                for name in [tag] if tag in lazy else computed[tag]:
                    target = _resolve_component(components, defaults, path, {**imports, **lazy}, name)
                    if target is not None and target != user:
                        links.add((user, target))
            for line in dynamic_route_lines(source):
                declarer = _declarer(context, file_id, rows, line)
                if declarer is not None:
                    partial.add(declarer)
        _mark_partial(context, partial)
        for user, target in sorted(links):
            _insert_relationship(context, "renders", user, target, confidence="low")

    def _declare_routes(self, context) -> None:
        """Mark components routed by react-router as pages, linked from the declaring code."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        context.conn.executemany(
            "UPDATE symbols SET metadata_json = json_remove(metadata_json, '$.routes')"
            " WHERE id = ?",
            [(row[0],) for rows in components.values() for row in rows],
        )
        context.conn.execute(
            "DELETE FROM relationships WHERE relationship_type = 'routes_to'"
            " AND source_entity_type = 'symbol'"
            " AND source_entity_id IN (SELECT s.id FROM symbols s JOIN files f"
            " ON f.id = s.file_id WHERE f.project_id = ?)",
            (context.project_id,),
        )
        routes: dict[int, set[str]] = {}
        links: set[tuple[int, int]] = set()
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            imports = self._imported_names(path, source)
            for route, tag, line in route_declarations(source):
                target = _resolve_component(components, defaults, path, imports, tag)
                declarer = _declarer(context, file_id, components.get(path, []), line)
                if target is None or declarer is None:
                    continue
                routes.setdefault(target, set()).add(route)
                links.add((declarer, target))
        for target, paths in routes.items():
            context.conn.execute(
                "UPDATE symbols SET metadata_json = json_set(COALESCE(metadata_json, '{}'),"
                " '$.framework_kind', 'react_page', '$.routes', json(?)) WHERE id = ?",
                (json.dumps(sorted(paths)), target),
            )
        for declarer, target in sorted(links):
            _insert_relationship(context, "routes_to", declarer, target)

    def _link_renders(self, context) -> None:
        """Link each component to the imported and same-file project components its JSX renders."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        component_ids = [(row[0],) for rows in components.values() for row in rows]
        context.conn.executemany(
            "DELETE FROM relationships WHERE relationship_type = 'renders'"
            " AND source_entity_type = 'symbol' AND source_entity_id = ?",
            component_ids,
        )
        context.conn.executemany(
            "UPDATE symbols SET metadata_json = json_remove(metadata_json, '$.partial')"
            " WHERE id = ?",
            component_ids,
        )
        partial: set[int] = set()
        for path, rows in components.items():
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            imports = self._imported_names(path, source)
            local = {name for _, name, _, _ in rows}
            shadowed = self._shadowed_tags(path, source)
            hiding_imports = self._shadowed_tags(path, source, functions=True)
            links: dict[tuple[int, int], str] = {}
            for tag, line in self._jsx_tags(path, source):
                row = next((row for row in rows if row[2] <= line <= row[3]), None)
                if row is None:
                    continue
                user, confidence = row[0], "high"
                if tag in imports and (tag, line) not in hiding_imports:
                    target = _resolve_component(components, defaults, path, imports, tag)
                elif tag in local and (tag, line) not in shadowed:
                    target = visible_component(rows, tag, line)
                    if self.backend == "regex" and tag in usages.names_outside_tags(source, row[2], row[3]):
                        # Without scopes, a name used outside tags may be a local binding.
                        confidence = "low"
                else:
                    continue
                if target is not None and target != user:
                    links[(user, target)] = confidence
                    if confidence == "low":
                        partial.add(user)
            for (user, target), confidence in sorted(links.items()):
                _insert_relationship(context, "renders", user, target, confidence)
        _mark_partial(context, partial)

    def _tag_components(self, context) -> None:
        """Tag the components the javascript plugin found in .js/.ts files, as pages in page locations."""
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            framework_kind = "react_page" if is_page_path(path) else "react_component"
            context.conn.execute(
                """
                UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'), '$.framework_kind', ?
                )
                WHERE file_id = ? AND kind = 'component'
                """,
                (framework_kind, file_id),
            )
