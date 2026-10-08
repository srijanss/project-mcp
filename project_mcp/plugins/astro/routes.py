from pathlib import PurePosixPath

_PAGES = ("src", "pages")
_PAGE_EXTENSIONS = {".astro", ".ts", ".js"}


def route_for(path: str) -> dict | None:
    """The route a file under src/pages serves, with its kind (static, dynamic
    for a `[param]` segment, rest for a `[...param]` one); None for any other
    file, or one a `_` prefix keeps out of routing."""
    parts = PurePosixPath(path).parts
    if parts[:2] != _PAGES or len(parts) < 3:
        return None
    segments = list(parts[2:])
    if any(segment.startswith("_") for segment in segments):
        return None
    last = PurePosixPath(segments[-1])
    if last.suffix not in _PAGE_EXTENSIONS:
        return None
    segments[-1] = last.stem
    if segments[-1] == "index":
        segments.pop()
    kind = "static"
    for segment in segments:
        if segment.startswith("[...") and segment.endswith("]"):
            kind = "rest"
        elif segment.startswith("[") and segment.endswith("]") and kind == "static":
            kind = "dynamic"
    return {"route": "/" + "/".join(segments), "route_kind": kind}
