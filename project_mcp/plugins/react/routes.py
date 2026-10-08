"""The routes a react file declares with react-router."""
import re

from project_mcp.plugins.react.usages import _without_comments

_ROUTE_TAG = re.compile(r"<Route(?=[\s/>])")
_PATH_ATTRIBUTE = re.compile(
    r"""(?<![\w$])path\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*["']([^"']*)["']\s*\})"""
)
_ELEMENT_ATTRIBUTE = re.compile(r"(?<![\w$])element\s*=\s*\{\s*<([A-Z][\w$]*)")
_ROUTER_CALL = re.compile(
    r"\b(?:create(?:Browser|Hash|Memory)Router|useRoutes|createRoutesFromElements)\b"
)
_PATH_THEN_ELEMENT = re.compile(
    r"""(?<![\w$])path\s*:\s*["']([^"']*)["']\s*,\s*element\s*:\s*<([A-Z][\w$]*)"""
)
_ELEMENT_KEY = re.compile(r"(?<![\w$])element\s*:\s*<([A-Z][\w$]*)")
_THEN_PATH = re.compile(r"""\s*,\s*path\s*:\s*["']([^"']*)["']""")


def _skip_quoted(code: str, index: int) -> int:
    """The index just past the string literal opening at `index`."""
    quote = code[index]
    index += 1
    while index < len(code) and code[index] != quote:
        index += 2 if code[index] == "\\" else 1
    return index + 1


def _tag_end(code: str, start: int) -> int:
    """The index of the `>` closing the tag whose attributes begin at `start`."""
    depth = 0
    index = start
    while index < len(code):
        char = code[index]
        if char in "\"'`":
            index = _skip_quoted(code, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth == 0:
            return index
        index += 1
    return len(code)


def _line(code: str, index: int) -> int:
    return code.count("\n", 0, index) + 1


def _jsx_routes(code: str) -> list[tuple[int, str, str]]:
    routes = []
    for tag in _ROUTE_TAG.finditer(code):
        attributes = code[tag.end() : _tag_end(code, tag.end())]
        element = _ELEMENT_ATTRIBUTE.search(attributes)
        if element is None:
            continue
        # The element's own props must not be mistaken for the route's path.
        own = attributes[: element.start()] + attributes[_tag_end(attributes, element.end()) :]
        path = _PATH_ATTRIBUTE.search(own)
        if path is not None:
            literal = next(group for group in path.groups() if group is not None)
            routes.append((tag.start(), literal, element[1]))
    return routes


def _config_routes(code: str) -> list[tuple[int, str, str]]:
    if not _ROUTER_CALL.search(code):
        return []
    routes = [(m.start(), m[1], m[2]) for m in _PATH_THEN_ELEMENT.finditer(code)]
    for element in _ELEMENT_KEY.finditer(code):
        path = _THEN_PATH.match(code, _tag_end(code, element.end()) + 1)
        if path is not None:
            routes.append((element.start(), path[1], element[1]))
    return routes


def route_declarations(source: str) -> list[tuple[str, str, int]]:
    """Each statically visible route as (path, element component name, line).

    Covers `<Route path element={<X />}>` and `{ path, element: <X /> }` objects
    in a file that creates a router; routes without a literal path or a
    component element are left out.
    """
    code = _without_comments(source)
    found = sorted(_jsx_routes(code) + _config_routes(code))
    return [(path, tag, _line(code, index)) for index, path, tag in found]
