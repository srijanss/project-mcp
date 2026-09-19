"""Tests for the naive-exploration baseline measurement (Approach A)."""

from project_mcp.benchmark.corpus import TASKS
from project_mcp.benchmark.naive_baseline import measure_naive_baseline


class TestNaiveBaselineMeasurement:
    """Approach A: a coding agent without Project MCP reads every file
    under the task's relevant directory/module scope."""

    def test_opens_every_file_under_the_relevant_scope_directories(self):
        task = next(t for t in TASKS if t.name == "order-cancellation-location")

        result = measure_naive_baseline(task)

        # scope = the directories containing the ground-truth files
        # ("shop/" and "tests/"), so the naive approach opens every file
        # in those directories, not just the ground-truth ones.
        assert "shop/orders.py" in result.files_opened
        assert "shop/payments.py" in result.files_opened
        assert "tests/test_orders.py" in result.files_opened
        assert "tests/test_payments.py" in result.files_opened

    def test_counts_total_bytes_and_a_whitespace_token_proxy(self):
        task = next(t for t in TASKS if t.name == "order-cancellation-location")

        result = measure_naive_baseline(task)

        assert result.total_bytes > 0
        assert result.total_tokens_proxy > 0
        assert result.total_tokens_proxy <= result.total_bytes

    def test_skips_files_that_cannot_be_decoded_as_text(self):
        task = next(t for t in TASKS if t.name == "dashboard-ui-bug")

        result = measure_naive_baseline(task)

        assert "shop/legacy_asset.bin" not in result.files_opened
        assert "shop/dashboard.py" in result.files_opened
