import re
from pathlib import Path

_STRUCT_RE = re.compile(r"^\s*(pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)")
_ENUM_RE = re.compile(r"^\s*(pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)")
_FN_RE = re.compile(
    r"^\s*(pub(?:\([^)]*\))?\s+)?"
    r"(?:(?:async|const|unsafe|extern(?:\s+\"[^\"]*\")?)\s+)*fn\s+([A-Za-z_]\w*)"
)
_TRAIT_RE = re.compile(
    r"^\s*(pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?trait\s+([A-Za-z_]\w*)"
)


def _module_qualified_name(path: str) -> str:
    module_path = Path(path).with_suffix("")
    return ".".join(module_path.parts)


def _visibility(pub_prefix: str | None) -> str:
    return "public" if pub_prefix else "private"


def parse_rust_source(path: str, source: str) -> list[dict]:
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

    for line_no, line in enumerate(source.splitlines(), start=1):
        struct_match = _STRUCT_RE.match(line)
        enum_match = _ENUM_RE.match(line)
        fn_match = _FN_RE.match(line)
        trait_match = _TRAIT_RE.match(line)

        if struct_match:
            name = struct_match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualified_name": f"{module_name}.{name}",
                    "kind": "struct",
                    "start_line": line_no,
                    "end_line": None,
                    "visibility": _visibility(struct_match.group(1)),
                }
            )
        elif enum_match:
            name = enum_match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualified_name": f"{module_name}.{name}",
                    "kind": "enum",
                    "start_line": line_no,
                    "end_line": None,
                    "visibility": _visibility(enum_match.group(1)),
                }
            )
        elif fn_match:
            name = fn_match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualified_name": f"{module_name}.{name}",
                    "kind": "function",
                    "start_line": line_no,
                    "end_line": None,
                    "visibility": _visibility(fn_match.group(1)),
                }
            )
        elif trait_match:
            name = trait_match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualified_name": f"{module_name}.{name}",
                    "kind": "trait",
                    "start_line": line_no,
                    "end_line": None,
                    "visibility": _visibility(trait_match.group(1)),
                }
            )

    return symbols


_USE_START_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+")


def _collect_use_statements(source: str) -> list[tuple[int, str]]:
    lines = source.splitlines()
    statements = []
    i = 0
    n = len(lines)
    while i < n:
        start_match = _USE_START_RE.match(lines[i])
        if not start_match:
            i += 1
            continue

        start_line_no = i + 1
        first_fragment = lines[i][start_match.end():]
        parts = [first_fragment]
        depth = first_fragment.count("{") - first_fragment.count("}")
        has_semicolon = ";" in first_fragment
        j = i
        while not (depth == 0 and has_semicolon):
            j += 1
            if j >= n:
                break
            fragment = lines[j]
            parts.append(fragment)
            depth += fragment.count("{") - fragment.count("}")
            has_semicolon = has_semicolon or ";" in fragment

        buffer = " ".join(parts)
        semi_idx = buffer.find(";")
        if semi_idx != -1:
            statements.append((start_line_no, buffer[:semi_idx].strip()))
        i = j + 1

    return statements


def _split_top_level(body: str) -> list[str]:
    parts = []
    depth = 0
    current = []
    for char in body:
        if char == "{":
            depth += 1
            current.append(char)
        elif char == "}":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _flatten_use_entries(prefix: str, body: str, results_by_path: dict) -> None:
    for entry in _split_top_level(body):
        brace_idx = entry.find("{")
        if brace_idx != -1:
            sub_prefix = entry[:brace_idx].rstrip(":").rstrip()
            inner = entry[brace_idx + 1 :].rstrip()
            if inner.endswith("}"):
                inner = inner[:-1]
            combined_prefix = f"{prefix}::{sub_prefix}" if sub_prefix else prefix
            _flatten_use_entries(combined_prefix, inner, results_by_path)
        elif "::" in entry:
            segments = entry.split("::")
            combined_prefix = f"{prefix}::{'::'.join(segments[:-1])}" if prefix else "::".join(segments[:-1])
            results_by_path.setdefault(combined_prefix, []).append(segments[-1])
        else:
            results_by_path.setdefault(prefix, []).append(entry)


def extract_rust_use(path: str, source: str) -> list[dict]:
    uses = []

    for line_no, full in _collect_use_statements(source):
        brace_idx = full.find("{")
        results_by_path: dict = {}

        if brace_idx == -1:
            segments = full.split("::")
            results_by_path["::".join(segments[:-1])] = [segments[-1]]
        else:
            prefix = full[:brace_idx].rstrip(":").rstrip()
            depth = 0
            end_idx = len(full)
            for i in range(brace_idx, len(full)):
                if full[i] == "{":
                    depth += 1
                elif full[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            body = full[brace_idx + 1 : end_idx]
            _flatten_use_entries(prefix, body, results_by_path)

        for entry_path, names in results_by_path.items():
            uses.append({"path": entry_path, "names": names, "line": line_no})

    return uses


_IMPL_START_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?impl\b")
_IDENT_RE = re.compile(r"[\w:]+")
_FOR_RE = re.compile(r"\s+for\s+")
_WHITESPACE_RE = re.compile(r"\s*")


def _skip_balanced_angle_brackets(line: str, index: int) -> int:
    if index >= len(line) or line[index] != "<":
        return index
    depth = 0
    for i in range(index, len(line)):
        if line[i] == "<":
            depth += 1
        elif line[i] == ">":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(line)


def _parse_impl_header(line: str) -> dict | None:
    start_match = _IMPL_START_RE.match(line)
    if not start_match:
        return None
    index = start_match.end()

    index += _WHITESPACE_RE.match(line, index).end() - index
    index = _skip_balanced_angle_brackets(line, index)
    index += _WHITESPACE_RE.match(line, index).end() - index

    first_ident = _IDENT_RE.match(line, index)
    if not first_ident:
        return None
    index = first_ident.end()
    index = _skip_balanced_angle_brackets(line, index)

    for_match = _FOR_RE.match(line, index)
    if for_match:
        index = for_match.end()
        second_ident = _IDENT_RE.match(line, index)
        if not second_ident:
            return None
        index = second_ident.end()
        index = _skip_balanced_angle_brackets(line, index)
        trait_name = first_ident.group()
        struct_name = second_ident.group()
    else:
        trait_name = None
        struct_name = first_ident.group()

    index += _WHITESPACE_RE.match(line, index).end() - index
    if index >= len(line) or line[index] != "{":
        return None

    return {"struct": struct_name, "trait": trait_name}


def extract_rust_impls(path: str, source: str) -> list[dict]:
    impls = []

    for line_no, line in enumerate(source.splitlines(), start=1):
        header = _parse_impl_header(line)
        if header is None:
            continue

        impls.append({"struct": header["struct"], "trait": header["trait"], "line": line_no})

    return impls
