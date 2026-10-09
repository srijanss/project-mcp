"""Which same-file component a JSX tag name refers to."""


def visible_component(rows, name: str, line: int) -> int | None:
    """The id of the component `name` that is in scope at `line`.

    `rows` are (id, name, start line, end line). A top-level component is
    visible throughout the file; a nested one only inside the component
    declaring it. When several are visible, the innermost declaration wins.
    """
    best = None
    for id_, component, start, end in rows:
        if component != name:
            continue
        parent = _enclosing(rows, id_, start, end)
        if parent is not None and not parent[0] <= line <= parent[1]:
            continue
        width = parent[1] - parent[0] if parent else float("inf")
        if best is None or width < best[0]:
            best = (width, id_)
    return best[1] if best else None


def _enclosing(rows, id_: int, start: int, end: int) -> tuple[int, int] | None:
    """The span of the smallest other component containing lines start..end."""
    spans = [
        (s, e) for other, _, s, e in rows if other != id_ and s <= start and end <= e and (s, e) != (start, end)
    ]
    return min(spans, key=lambda span: span[1] - span[0], default=None)
