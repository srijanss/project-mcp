import re
from pathlib import Path

_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?function\s+([A-Za-z_$][\w$]*)\s*\("
)
_ARROW_CONST_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_CLASS_RE = re.compile(r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)")
_METHOD_RE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*\(")
_JSX_RETURN_RE = re.compile(r"return\s*\(?\s*<")
_PASCAL_CASE_RE = re.compile(r"^[A-Z][\w$]*$")


def _is_component(name: str, lines: list[str], start_index: int) -> bool:
    if not _PASCAL_CASE_RE.match(name):
        return False

    depth = 0
    for index in range(start_index, len(lines)):
        line = lines[index].split("//", 1)[0]
        if _JSX_RETURN_RE.search(line) or line.strip().startswith("<"):
            return True
        depth += line.count("{") - line.count("}")
        if index > start_index and depth <= 0:
            break
    return False


def _module_qualified_name(path: str) -> str:
    module_path = Path(path).with_suffix("")
    return ".".join(module_path.parts)


def parse_js_source(path: str, source: str) -> list[dict]:
    module_name = _module_qualified_name(path)
    symbols = [
        {
            "name": module_name,
            "qualified_name": module_name,
            "kind": "module",
            "start_line": 1,
            "end_line": len(source.splitlines()) or 1,
            "visibility": "public",
        }
    ]

    lines = source.splitlines()
    current_class = None
    class_brace_depth = None
    depth = 0

    for line_no, line in enumerate(lines, start=1):
        class_match = _CLASS_RE.match(line)
        if class_match:
            name = class_match.group(1)
            qualified_name = f"{module_name}.{name}"
            symbols.append(
                {
                    "name": name,
                    "qualified_name": qualified_name,
                    "kind": "class",
                    "start_line": line_no,
                    "end_line": None,
                    "visibility": "public",
                }
            )
            current_class = qualified_name
            class_brace_depth = depth
        elif current_class is not None:
            method_match = _METHOD_RE.match(line)
            if method_match and depth == class_brace_depth + 1:
                name = method_match.group(1)
                symbols.append(
                    {
                        "name": name,
                        "qualified_name": f"{current_class}.{name}",
                        "kind": "method",
                        "start_line": line_no,
                        "end_line": None,
                        "visibility": "public",
                    }
                )
        else:
            func_match = _FUNCTION_RE.match(line) or _ARROW_CONST_RE.match(line)
            if func_match:
                name = func_match.group(1)
                kind = (
                    "component"
                    if _is_component(name, lines, line_no - 1)
                    else "function"
                )
                symbols.append(
                    {
                        "name": name,
                        "qualified_name": f"{module_name}.{name}",
                        "kind": kind,
                        "start_line": line_no,
                        "end_line": None,
                        "visibility": "public",
                    }
                )

        depth += line.count("{") - line.count("}")
        if current_class is not None and depth <= class_brace_depth:
            current_class = None
            class_brace_depth = None

    return symbols


_STATIC_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:(?P<default>[A-Za-z_$][\w$]*)\s*(?:,\s*)?)?"
    r"(?:\{\s*(?P<named>[^}]*)\s*\}\s*)?"
    r"(?:from\s+)?['\"](?P<module>[^'\"]+)['\"]"
)
_REQUIRE_RE = re.compile(r"require\(\s*['\"`](?P<module>[^'\"`]+)['\"`]\s*\)")
_DYNAMIC_IMPORT_RE = re.compile(r"import\(\s*['\"`](?P<module>[^'\"`]+)['\"`]\s*\)")


def extract_js_imports(path: str, source: str) -> list[dict]:
    imports = []

    for line_no, line in enumerate(source.splitlines(), start=1):
        dynamic_match = _DYNAMIC_IMPORT_RE.search(line)
        require_match = _REQUIRE_RE.search(line)
        if dynamic_match:
            imports.append(
                {
                    "module": dynamic_match.group("module"),
                    "names": [],
                    "default": None,
                    "line": line_no,
                    "dynamic": True,
                }
            )
            continue
        if require_match:
            imports.append(
                {
                    "module": require_match.group("module"),
                    "names": [],
                    "default": None,
                    "line": line_no,
                    "dynamic": True,
                }
            )
            continue

        static_match = _STATIC_IMPORT_RE.match(line)
        if static_match:
            named = static_match.group("named")
            names = (
                [n.split(" as ")[0].strip() for n in named.split(",") if n.strip()]
                if named
                else []
            )
            imports.append(
                {
                    "module": static_match.group("module"),
                    "names": names,
                    "default": static_match.group("default"),
                    "line": line_no,
                }
            )

    return imports


_EXPORT_NAMED_DECL_RE = re.compile(
    r"^\s*export\s+(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)"
)
_EXPORT_DEFAULT_RE = re.compile(r"^\s*export\s+default\s+([A-Za-z_$][\w$]*)")
_EXPORT_LIST_RE = re.compile(r"^\s*export\s*\{\s*([^}]*)\s*\}")
_EXPORT_LIST_OPEN_RE = re.compile(r"^\s*export\s*\{")


def extract_js_exports(path: str, source: str) -> list[dict]:
    exports = []

    lines = source.splitlines()
    line_no = 0
    while line_no < len(lines):
        line_no += 1
        line = lines[line_no - 1]

        default_match = _EXPORT_DEFAULT_RE.match(line)
        if default_match:
            exports.append(
                {"name": default_match.group(1), "kind": "default", "line": line_no}
            )
            continue

        named_decl_match = _EXPORT_NAMED_DECL_RE.match(line)
        if named_decl_match:
            exports.append(
                {"name": named_decl_match.group(1), "kind": "named", "line": line_no}
            )
            continue

        if _EXPORT_LIST_OPEN_RE.match(line) and "}" not in line:
            start_line_no = line_no
            body = line
            while line_no < len(lines) and "}" not in lines[line_no]:
                line_no += 1
                body += "\n" + lines[line_no - 1]
            if line_no < len(lines):
                line_no += 1
                body += "\n" + lines[line_no - 1]
            list_match = _EXPORT_LIST_RE.match(body)
            if list_match:
                for entry in list_match.group(1).split(","):
                    name = entry.strip().split(" as ")[0].strip()
                    if name:
                        exports.append(
                            {"name": name, "kind": "named", "line": start_line_no}
                        )
            continue

        list_match = _EXPORT_LIST_RE.match(line)
        if list_match:
            for entry in list_match.group(1).split(","):
                name = entry.strip().split(" as ")[0].strip()
                if name:
                    exports.append({"name": name, "kind": "named", "line": line_no})

    return exports
