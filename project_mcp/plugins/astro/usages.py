import re

_DEFAULT_IMPORT = re.compile(
    r"""(?<![\w$.])import\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:,\s*(?:\{[^}]*\}|\*\s+as\s+[\w$]+))?"""
    r"""\s+from\s+["'](?P<specifier>[^"']+)["']"""
)
_NAMED_IMPORT = re.compile(
    r"""(?<![\w$.])import\s+(?!type\b)(?:[A-Za-z_$][\w$]*\s*,\s*)?\{(?P<named>[^}]*)\}"""
    r"""\s*from\s+["'](?P<specifier>[^"']+)["']"""
)
# Text that is not markup: HTML comments, `{/* */}` expression comments, and
# the bodies of <script> and <style> elements.
_NOT_MARKUP = re.compile(
    r"<!--.*?-->|\{\s*/\*.*?\*/\s*\}|<(script|style)\b[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
# A capitalised tag name, not a member (`<Foo.Bar>`) or namespaced one.
_COMPONENT_TAG = re.compile(r"<([A-Z][\w$]*)(?=[\s/>])")


def default_imports(script: str) -> dict[str, str]:
    """The module specifier behind each default-imported name in a frontmatter script."""
    return {m["name"]: m["specifier"] for m in _DEFAULT_IMPORT.finditer(script)}


def rendered_tags(template: str) -> set[str]:
    """The component names a template renders: its capitalised tags."""
    return set(_COMPONENT_TAG.findall(_NOT_MARKUP.sub(" ", template)))


def named_imports(script: str) -> dict[str, tuple[str, str]]:
    """The (module specifier, exported name) behind each name a frontmatter script imports by name."""
    names: dict[str, tuple[str, str]] = {}
    for match in _NAMED_IMPORT.finditer(script):
        for item in match["named"].split(","):
            parts = item.split()
            if parts and parts[0] != "type":
                names[parts[-1]] = (match["specifier"], parts[0])
    return names
