"""What a react source file imports and which JSX tags it renders."""
import posixpath
import re

_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
# A string literal (kept, so a `//` inside it is not a comment) or a comment.
_STRING_OR_COMMENT = re.compile(
    r"""("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|//[^\n]*|/\*.*?\*/""",
    re.DOTALL,
)
_IMPORT = re.compile(
    r"""^[ \t]*import\s+(?!type\b)(?P<clause>[^'";]+?)\s+from\s+["'](?P<specifier>[^"']+)["']""",
    re.MULTILINE,
)
_CLAUSE = re.compile(
    r"""\s*(?P<default>[A-Za-z_$][\w$]*)?\s*,?\s*(?:\{(?P<named>[^}]*)\})?\s*(?:\*\s+as\s+[\w$]+)?\s*$"""
)
# A capitalised tag name, not a member (`<Foo.Bar>`), a closing tag, or a
# generic argument or call (`useState<Item>(`), which follow an identifier.
_COMPONENT_TAG = re.compile(r"(?<![\w$.)\]])<([A-Z][\w$]*)(?=[\s/>])")


def _without_comments(source: str) -> str:
    """The source with comments blanked out, keeping every line number."""

    def blank(match: re.Match) -> str:
        return match[1] if match[1] else "\n" * match[0].count("\n")

    return _STRING_OR_COMMENT.sub(blank, source)


def imported_names(source: str) -> dict[str, tuple[str, str]]:
    """The (module specifier, imported name) behind each local name a file imports.

    A default import has the imported name "default"; namespace and type-only
    imports are left out.
    """
    names: dict[str, tuple[str, str]] = {}
    for match in _IMPORT.finditer(_without_comments(source)):
        clause = _CLAUSE.match(match["clause"])
        if clause is None:
            continue
        specifier = match["specifier"]
        if clause["default"]:
            names[clause["default"]] = (specifier, "default")
        for item in (clause["named"] or "").split(","):
            parts = item.split()
            if not parts or parts[0] == "type":
                continue
            names[parts[-1]] = (specifier, parts[0])
    return names


def jsx_tags(source: str) -> list[tuple[str, int]]:
    """Each capitalised JSX tag name with the line it opens on."""
    code = _without_comments(source)
    return [
        (match[1], code.count("\n", 0, match.start()) + 1)
        for match in _COMPONENT_TAG.finditer(code)
    ]


def import_candidates(importer: str, specifier: str) -> list[str]:
    """Candidate files for a relative module specifier; bare packages resolve to none."""
    if not specifier.startswith("."):
        return []
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
    if base.endswith(_EXTENSIONS):
        return [base]
    return [base + ext for ext in _EXTENSIONS] + [f"{base}/index{ext}" for ext in _EXTENSIONS]
