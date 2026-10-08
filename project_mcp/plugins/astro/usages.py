import re

_DEFAULT_IMPORT = re.compile(
    r"""(?<![\w$.])import\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:,\s*(?:\{[^}]*\}|\*\s+as\s+[\w$]+))?"""
    r"""\s+from\s+["'](?P<specifier>[^"']+)["']"""
)
# A capitalised tag name, not a member (`<Foo.Bar>`) or namespaced one.
_COMPONENT_TAG = re.compile(r"<([A-Z][\w$]*)(?=[\s/>])")


def default_imports(script: str) -> dict[str, str]:
    """The module specifier behind each default-imported name in a frontmatter script."""
    return {m["name"]: m["specifier"] for m in _DEFAULT_IMPORT.finditer(script)}


def rendered_tags(template: str) -> set[str]:
    """The component names a template renders: its capitalised tags."""
    return set(_COMPONENT_TAG.findall(template))
