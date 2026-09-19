"""Tests for the Project MCP-assisted measurement (Approach B)."""

import pytest

from project_mcp.benchmark.corpus import BenchmarkTask, FIXTURE_PROJECT_ROOT, TASKS
from project_mcp.benchmark.context_pack_measurement import measure_context_pack


class TestContextPackMeasurement:
    """Approach B: call the task's get_context_for_* tool and measure the
    resulting context pack's size and precision/recall against the
    ground-truth relevant file set."""

    def test_recommended_files_overlap_the_ground_truth_for_a_symbol_task(self):
        task = next(t for t in TASKS if t.name == "payment-capture-tests")

        result = measure_context_pack(task)

        assert "shop/payments.py" in result.recommended_files
        assert 0.0 <= result.precision <= 1.0
        assert 0.0 <= result.recall <= 1.0
        assert result.recall > 0.0

    def test_measures_the_context_pack_size(self):
        task = next(t for t in TASKS if t.name == "order-cancellation-location")

        result = measure_context_pack(task)

        assert result.pack_bytes > 0
        assert result.pack_tokens_proxy > 0
        assert result.pack_tokens_proxy <= result.pack_bytes

    def test_raises_when_the_context_pack_tool_reports_an_error_status(self):
        task = BenchmarkTask(
            name="broken-symbol-lookup",
            task_type="find_symbol_location",
            query="",
            context_pack_tool="get_context_for_symbol",
            context_pack_args={"qualified_name": ""},
            relevant_files=frozenset({"shop/orders.py"}),
        )

        with pytest.raises(RuntimeError, match="broken-symbol-lookup"):
            measure_context_pack(task)

    def test_raises_a_clear_error_for_an_unknown_context_pack_tool_name(self):
        task = BenchmarkTask(
            name="typo-tool-name",
            task_type="find_symbol_location",
            query="",
            context_pack_tool="get_context_for_nonexistent_tool",
            context_pack_args={},
            relevant_files=frozenset({"shop/orders.py"}),
        )

        with pytest.raises(ValueError, match="get_context_for_nonexistent_tool"):
            measure_context_pack(task)
