"""Pure detection of legacy-code signals (MVP 11).

Each detector returns evidence-backed signals matching the legacy_signals
schema: {"target", "signal", "severity", "confidence", "evidence"}. No
verdict language, no DB access — callers (the indexer) supply the data and
persist the results.
"""

from collections import deque

from project_mcp.config import ProjectConfig


def detect_structural_signals(
    files: list[dict], symbols: list[dict], config: ProjectConfig
) -> list[dict]:
    """Detect large_file, large_symbol, and explicit_legacy_path signals.

    Args:
        files: list of {"path": str, "line_count": int}
        symbols: list of {"qualified_name": str, "start_line": int, "end_line": int}
        config: project config providing thresholds and legacy_paths

    Returns:
        List of signal dicts matching the legacy_signals schema.
    """
    signals = []

    for file_entry in files:
        path = file_entry["path"]
        line_count = file_entry["line_count"]

        if line_count > config.large_file_lines:
            signals.append(
                {
                    "target": path,
                    "signal": "large_file",
                    "severity": "medium",
                    "confidence": "high",
                    "evidence": [
                        f"{line_count} lines exceeds threshold of {config.large_file_lines}"
                    ],
                }
            )

        if any(path.startswith(legacy_path) for legacy_path in config.legacy_paths):
            signals.append(
                {
                    "target": path,
                    "signal": "explicit_legacy_path",
                    "severity": "high",
                    "confidence": "high",
                    "evidence": [f"{path} matches a configured legacy path"],
                }
            )

    for symbol in symbols:
        symbol_line_count = symbol["end_line"] - symbol["start_line"] + 1
        if symbol_line_count > config.large_symbol_lines:
            signals.append(
                {
                    "target": symbol["qualified_name"],
                    "signal": "large_symbol",
                    "severity": "medium",
                    "confidence": "high",
                    "evidence": [
                        f"{symbol_line_count} lines exceeds threshold of "
                        f"{config.large_symbol_lines}"
                    ],
                }
            )

    return signals


def detect_fan_signals(targets: list[dict], config: ProjectConfig) -> list[dict]:
    """Detect high_fan_in and high_fan_out signals from dependency counts.

    Args:
        targets: list of {"target": str, "fan_in": int, "fan_out": int}
        config: project config providing fan-in/fan-out thresholds

    Returns:
        List of signal dicts matching the legacy_signals schema.
    """
    signals = []
    for entry in targets:
        target = entry["target"]
        fan_in = entry["fan_in"]
        fan_out = entry["fan_out"]

        if fan_in > config.high_fan_in_count:
            signals.append(
                {
                    "target": target,
                    "signal": "high_fan_in",
                    "severity": "medium",
                    "confidence": "high",
                    "evidence": [
                        f"{fan_in} dependents exceeds threshold of {config.high_fan_in_count}"
                    ],
                }
            )

        if fan_out > config.high_fan_out_count:
            signals.append(
                {
                    "target": target,
                    "signal": "high_fan_out",
                    "severity": "medium",
                    "confidence": "high",
                    "evidence": [
                        f"{fan_out} dependencies exceeds threshold of "
                        f"{config.high_fan_out_count}"
                    ],
                }
            )

    return signals


def detect_circular_dependency_signals(edges: list[tuple[str, str]]) -> list[dict]:
    """Detect circular_dependency signals via cycle detection over a directed graph.

    Args:
        edges: list of (source, target) pairs meaning source depends on target

    Returns:
        One signal per node participating in at least one cycle.
    """
    graph: dict[str, list[str]] = {}
    for source, target in edges:
        graph.setdefault(source, []).append(target)
        graph.setdefault(target, [])

    cyclic = {
        node: members
        for component in _strongly_connected_components(graph)
        if len(component) > 1 or component[0] in graph[component[0]]
        for members in [set(component)]
        for node in component
    }
    return [
        {
            "target": node,
            "signal": "circular_dependency",
            "severity": "high",
            "confidence": "high",
            "evidence": [f"cycle: {' -> '.join(_shortest_cycle(graph, node, cyclic[node]))}"],
        }
        for node in graph
        if node in cyclic
    ]


def _strongly_connected_components(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's algorithm, iterative: O(V + E) with no recursion depth limit
    (a recursive walk blows the Python call stack on long chains)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)

    for root in graph:
        if root in index:
            continue
        visit(root)
        work = [(root, iter(graph[root]))]
        while work:
            node, neighbors = work[-1]
            for neighbor in neighbors:
                if neighbor not in index:
                    visit(neighbor)
                    work.append((neighbor, iter(graph[neighbor])))
                    break
                if neighbor in on_stack:
                    low[node] = min(low[node], index[neighbor])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    components.append(component)
    return components


def _shortest_cycle(graph: dict[str, list[str]], node: str, component: set[str]) -> list[str]:
    """The shortest cycle through `node` that stays inside its component."""
    previous: dict[str, str | None] = {node: None}
    queue = deque([node])
    while queue:
        current = queue.popleft()
        for neighbor in graph[current]:
            if neighbor == node:
                path = [current]
                while previous[path[-1]] is not None:
                    path.append(previous[path[-1]])
                return [*reversed(path), node]
            if neighbor in component and neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    raise AssertionError(f"{node} is in a cyclic component but on no cycle")


def detect_churn_signals(targets: list[dict], config: ProjectConfig) -> list[dict]:
    """Detect high_churn signals from git change-count data.

    Args:
        targets: list of {"target": str, "change_count": int}
        config: project config providing the high_churn_count threshold

    Returns:
        List of signal dicts matching the legacy_signals schema.
    """
    signals = []
    for entry in targets:
        change_count = entry["change_count"]
        if change_count > config.high_churn_count:
            signals.append(
                {
                    "target": entry["target"],
                    "signal": "high_churn",
                    "severity": "medium",
                    "confidence": "high",
                    "evidence": [
                        f"{change_count} changes exceeds threshold of {config.high_churn_count}"
                    ],
                }
            )
    return signals


def detect_temporal_coupling_signals(targets: list[dict], config: ProjectConfig) -> list[dict]:
    """Detect high_temporal_coupling signals from git co-change data.

    Args:
        targets: list of {"target": str, "coupled_file_count": int}
        config: project config providing the high_temporal_coupling_count threshold

    Returns:
        List of signal dicts matching the legacy_signals schema.
    """
    signals = []
    for entry in targets:
        coupled_file_count = entry["coupled_file_count"]
        if coupled_file_count > config.high_temporal_coupling_count:
            signals.append(
                {
                    "target": entry["target"],
                    "signal": "high_temporal_coupling",
                    "severity": "medium",
                    "confidence": "high",
                    "evidence": [
                        f"{coupled_file_count} co-changed files exceeds threshold of "
                        f"{config.high_temporal_coupling_count}"
                    ],
                }
            )
    return signals


def detect_test_signals(targets: list[dict]) -> list[dict]:
    """Detect weak_test_relationship signals from test coverage data.

    Args:
        targets: list of {"target": str, "test_count": int, "confidences": list[str],
            "analyzed": bool}
            confidences holds the confidence ('high'/'medium'/'low') of each
            test relationship found for that target. `analyzed` (default True)
            is False when no plugin analyzed the target.

    Returns:
        List of weak_test_relationship signal dicts for targets with no
        tests, or only low/medium-confidence tests. An unanalyzed target's
        test relationships are unknown, never absent.
    """
    signals = []
    for entry in targets:
        target = entry["target"]
        test_count = entry["test_count"]
        confidences = entry.get("confidences", [])

        if not entry.get("analyzed", True):
            signals.append(
                {
                    "target": target,
                    "signal": "weak_test_relationship",
                    "severity": "medium",
                    "confidence": "unknown",
                    "evidence": [
                        "no active plugin analyzed this file, so its test"
                        " relationships are unknown"
                    ],
                }
            )
        elif test_count == 0:
            signals.append(
                {
                    "target": target,
                    "signal": "weak_test_relationship",
                    "severity": "high",
                    "confidence": "high",
                    "evidence": ["no test relationship found for this target"],
                }
            )
        elif "high" not in confidences:
            signals.append(
                {
                    "target": target,
                    "signal": "weak_test_relationship",
                    "severity": "medium",
                    "confidence": "medium",
                    "evidence": [
                        f"{test_count} test relationship(s) found, "
                        f"none at high confidence (confidences: {confidences})"
                    ],
                }
            )

    return signals
