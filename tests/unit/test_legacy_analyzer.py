from project_mcp.config import ProjectConfig
from project_mcp.analyzers.generic.legacy import (
    detect_churn_signals,
    detect_circular_dependency_signals,
    detect_fan_signals,
    detect_structural_signals,
    detect_temporal_coupling_signals,
    detect_test_signals,
)


def test_detect_test_signals_flags_target_with_no_tests():
    targets = [{"target": "app/models.py", "test_count": 0, "confidences": []}]

    signals = detect_test_signals(targets)

    assert len(signals) == 1
    assert signals[0]["target"] == "app/models.py"
    assert signals[0]["signal"] == "weak_test_relationship"
    assert signals[0]["severity"] == "high"
    assert signals[0]["confidence"] == "high"
    assert signals[0]["evidence"]


def test_detect_test_signals_flags_target_with_only_low_confidence_tests():
    targets = [
        {"target": "app/utils.py", "test_count": 2, "confidences": ["low", "low"]}
    ]

    signals = detect_test_signals(targets)

    assert len(signals) == 1
    assert signals[0]["target"] == "app/utils.py"
    assert signals[0]["signal"] == "weak_test_relationship"
    assert signals[0]["severity"] == "medium"
    assert signals[0]["confidence"] == "medium"


def test_detect_test_signals_does_not_flag_target_with_high_confidence_tests():
    targets = [
        {"target": "app/views.py", "test_count": 3, "confidences": ["high", "medium"]}
    ]

    signals = detect_test_signals(targets)

    assert signals == []


def _config(**overrides):
    return ProjectConfig(project_root="/tmp/project", **overrides)


def test_detect_structural_signals_flags_large_file():
    config = _config(large_file_lines=500)
    files = [{"path": "app/big.py", "line_count": 800}]

    signals = detect_structural_signals(files=files, symbols=[], config=config)

    assert len(signals) == 1
    assert signals[0]["target"] == "app/big.py"
    assert signals[0]["signal"] == "large_file"
    assert signals[0]["severity"] == "medium"
    assert signals[0]["confidence"] == "high"
    assert "800" in signals[0]["evidence"][0]


def test_detect_structural_signals_flags_large_symbol():
    config = _config(large_symbol_lines=100)
    symbols = [
        {"qualified_name": "app.big.BigClass.method", "start_line": 10, "end_line": 250}
    ]

    signals = detect_structural_signals(files=[], symbols=symbols, config=config)

    assert len(signals) == 1
    assert signals[0]["target"] == "app.big.BigClass.method"
    assert signals[0]["signal"] == "large_symbol"
    assert signals[0]["severity"] == "medium"
    assert signals[0]["confidence"] == "high"


def test_detect_structural_signals_flags_explicit_legacy_path():
    config = _config(legacy_paths=["app/legacy/"])
    files = [{"path": "app/legacy/old.py", "line_count": 10}]

    signals = detect_structural_signals(files=files, symbols=[], config=config)

    legacy_signals = [s for s in signals if s["signal"] == "explicit_legacy_path"]
    assert len(legacy_signals) == 1
    assert legacy_signals[0]["target"] == "app/legacy/old.py"
    assert legacy_signals[0]["severity"] == "high"
    assert legacy_signals[0]["confidence"] == "high"


def test_detect_structural_signals_ignores_files_and_symbols_under_threshold():
    config = _config(large_file_lines=500, large_symbol_lines=100)
    files = [{"path": "app/small.py", "line_count": 50}]
    symbols = [
        {"qualified_name": "app.small.fn", "start_line": 1, "end_line": 10}
    ]

    signals = detect_structural_signals(files=files, symbols=symbols, config=config)

    assert signals == []


def test_detect_fan_signals_flags_high_fan_in_and_high_fan_out():
    config = _config(high_fan_in_count=15, high_fan_out_count=15)
    targets = [{"target": "app.core", "fan_in": 20, "fan_out": 3}]

    signals = detect_fan_signals(targets, config=config)

    assert len(signals) == 1
    assert signals[0]["target"] == "app.core"
    assert signals[0]["signal"] == "high_fan_in"
    assert signals[0]["confidence"] == "high"
    assert "20" in signals[0]["evidence"][0]


def test_detect_fan_signals_ignores_targets_under_threshold():
    config = _config(high_fan_in_count=15, high_fan_out_count=15)
    targets = [{"target": "app.leaf", "fan_in": 1, "fan_out": 1}]

    signals = detect_fan_signals(targets, config=config)

    assert signals == []


def test_detect_circular_dependency_signals_flags_cycle_participants():
    edges = [("app.a", "app.b"), ("app.b", "app.c"), ("app.c", "app.a")]

    signals = detect_circular_dependency_signals(edges)

    targets = {s["target"] for s in signals}
    assert targets == {"app.a", "app.b", "app.c"}
    for signal in signals:
        assert signal["signal"] == "circular_dependency"
        assert signal["severity"] == "high"
        assert signal["confidence"] == "high"
        assert signal["evidence"]


def test_detect_circular_dependency_signals_flags_self_loop():
    edges = [("app.a", "app.a")]

    signals = detect_circular_dependency_signals(edges)

    assert len(signals) == 1
    assert signals[0]["target"] == "app.a"
    assert signals[0]["signal"] == "circular_dependency"


def test_detect_circular_dependency_signals_handles_long_acyclic_chain_without_crashing():
    chain = [(f"app.mod{i}", f"app.mod{i + 1}") for i in range(3000)]

    signals = detect_circular_dependency_signals(chain)

    assert signals == []


def test_detect_circular_dependency_signals_ignores_acyclic_graph():
    edges = [("app.a", "app.b"), ("app.b", "app.c")]

    signals = detect_circular_dependency_signals(edges)

    assert signals == []


def test_detect_churn_signals_flags_high_churn_file():
    config = _config(high_churn_count=20)
    targets = [{"target": "app/hot.py", "change_count": 35}]

    signals = detect_churn_signals(targets, config=config)

    assert len(signals) == 1
    assert signals[0]["target"] == "app/hot.py"
    assert signals[0]["signal"] == "high_churn"
    assert signals[0]["severity"] == "medium"
    assert signals[0]["confidence"] == "high"
    assert "35" in signals[0]["evidence"][0]


def test_detect_churn_signals_ignores_low_churn_file():
    config = _config(high_churn_count=20)
    targets = [{"target": "app/stable.py", "change_count": 2}]

    signals = detect_churn_signals(targets, config=config)

    assert signals == []


def test_detect_temporal_coupling_signals_flags_widely_coupled_file():
    config = _config(high_temporal_coupling_count=5)
    targets = [{"target": "app/shared.py", "coupled_file_count": 8}]

    signals = detect_temporal_coupling_signals(targets, config=config)

    assert len(signals) == 1
    assert signals[0]["target"] == "app/shared.py"
    assert signals[0]["signal"] == "high_temporal_coupling"
    assert signals[0]["severity"] == "medium"
    assert signals[0]["confidence"] == "high"
    assert "8" in signals[0]["evidence"][0]


def test_detect_temporal_coupling_signals_ignores_lightly_coupled_file():
    config = _config(high_temporal_coupling_count=5)
    targets = [{"target": "app/isolated.py", "coupled_file_count": 1}]

    signals = detect_temporal_coupling_signals(targets, config=config)

    assert signals == []


def test_detect_circular_dependency_signals_handles_dense_layered_graph_quickly():
    """A fully-connected layered DAG has an exponential number of distinct
    paths (15 layers x 15 nodes ~= 15**13 paths from one source to a sink).
    A naive path-copying DFS that re-explores every path would never finish;
    the O(V+E) three-color DFS should handle it in well under a second."""
    import time

    layers = [[f"mod_{layer}_{node}" for node in range(15)] for layer in range(15)]
    edges = [
        (source, target)
        for layer_idx in range(len(layers) - 1)
        for source in layers[layer_idx]
        for target in layers[layer_idx + 1]
    ]

    start = time.monotonic()
    signals = detect_circular_dependency_signals(edges)
    elapsed = time.monotonic() - start

    assert signals == []
    assert elapsed < 2.0
