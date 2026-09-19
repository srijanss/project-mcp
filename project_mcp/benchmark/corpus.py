"""Hand-labeled benchmark task corpus for the MVP14 token-efficiency benchmark."""

from dataclasses import dataclass, field
from pathlib import Path

FIXTURE_PROJECT_ROOT = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "benchmark" / "shop_project"
)


@dataclass(frozen=True)
class BenchmarkTask:
    name: str
    task_type: str
    query: str
    context_pack_tool: str
    context_pack_args: dict
    relevant_files: frozenset[str] = field(default_factory=frozenset)


TASKS = (
    BenchmarkTask(
        name="order-cancellation-location",
        task_type="find_symbol_location",
        query="Where does order cancellation belong?",
        context_pack_tool="get_context_for_feature",
        context_pack_args={"query": "order cancellation"},
        relevant_files=frozenset({"shop/orders.py", "tests/test_orders.py"}),
    ),
    BenchmarkTask(
        name="payment-capture-tests",
        task_type="find_related_tests",
        query="Find tests related to payment capture.",
        context_pack_tool="get_context_for_symbol",
        context_pack_args={"qualified_name": "shop.payments.capture_payment"},
        relevant_files=frozenset({"shop/payments.py", "tests/test_payments.py"}),
    ),
    BenchmarkTask(
        name="understand-checkout-legacy",
        task_type="understand_legacy_module",
        query="Understand the checkout legacy module.",
        context_pack_tool="get_context_for_refactor",
        context_pack_args={"target": "shop.checkout_legacy"},
        relevant_files=frozenset({"shop/checkout_legacy.py"}),
    ),
    BenchmarkTask(
        name="dashboard-ui-bug",
        task_type="identify_bug_relevant_files",
        query="Identify files relevant to a UI bug in the order dashboard.",
        context_pack_tool="get_context_for_bug",
        context_pack_args={"query": "order dashboard status label bug"},
        relevant_files=frozenset({"shop/dashboard.py"}),
    ),
    BenchmarkTask(
        name="architecture-discussion",
        task_type="prepare_architecture_context",
        query="Prepare context for an architecture discussion about the shop project.",
        context_pack_tool="get_context_for_architecture",
        context_pack_args={"area": "shop"},
        relevant_files=frozenset(
            {
                "ARCHITECTURE.md",
                "shop/orders.py",
                "shop/payments.py",
                "shop/checkout_legacy.py",
            }
        ),
    ),
)
