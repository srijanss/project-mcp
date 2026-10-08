"""Dynamic react patterns whose targets cannot be known statically."""
import re

from project_mcp.plugins.react.usages import _without_comments

_LAZY = re.compile(
    r"""(?:const|let|var)\s+([A-Z][\w$]*)\s*=\s*(?:React\s*\.\s*)?lazy\(\s*\(\s*\)\s*=>\s*"""
    r"""import\(\s*["']([^"']+)["']\s*\)\s*\)"""
)
_COMPUTED = re.compile(r"(?:const|let|var)\s+([A-Z][\w$]*)\s*=\s*([^;\n]*\?[^;\n]*)")
_CHOICE = re.compile(r"[?:]\s*([A-Z][\w$]*)\s*(?=:|$)")
_ROUTE_TAG = re.compile(r"<Route(?=[\s/>])")
_ROUTER_CALL = re.compile(
    r"\b(?:create(?:Browser|Hash|Memory)Router|useRoutes|createRoutesFromElements)\b"
)
_SPREAD_ENTRY = re.compile(r"(?m)^[ \t]*(\.\.\.[\w$.]+)[ \t]*,?[ \t]*$")


def lazy_imports(source: str) -> dict[str, str]:
    """The module each `lazy(() => import(...))` component is loaded from."""
    return {name: module for name, module in _LAZY.findall(_without_comments(source))}


def computed_components(source: str) -> dict[str, list[str]]:
    """Capitalised variables that pick between several components with a conditional."""
    computed = {}
    for name, expression in _COMPUTED.findall(_without_comments(source)):
        candidates = _CHOICE.findall(expression.strip())
        if len(candidates) > 1:
            computed[name] = candidates
    return computed


def _tag_end(code: str, start: int) -> int:
    depth = 0
    for index in range(start, len(code)):
        char = code[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth == 0:
            return index
    return len(code)


def dynamic_route_lines(source: str) -> list[int]:
    """Lines of route declarations built from spreads or non-literal paths."""
    code = _without_comments(source)
    lines = []
    for tag in _ROUTE_TAG.finditer(code):
        attributes = code[tag.end() : _tag_end(code, tag.end())]
        if "{..." in attributes or re.search(r"\bpath\s*=\s*\{\s*[^\s\"'}]", attributes):
            lines.append(code.count("\n", 0, tag.start()) + 1)
    if _ROUTER_CALL.search(code):
        lines += [code.count("\n", 0, m.start(1)) + 1 for m in _SPREAD_ENTRY.finditer(code)]
    return sorted(lines)
