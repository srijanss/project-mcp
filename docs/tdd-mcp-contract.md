# TDD MCP integration contract

Project MCP provides project facts to TDD MCP through the `get_context_for_*`
tools. Clients never need direct SQLite access.

## Fields provided

Both `get_context_for_feature(query)` and `get_context_for_symbol(target)`
return these stable top-level fields:

- `related_tests`: tests related to the target.
- `entrypoints`: entrypoints relevant to the target (currently always empty; detection is not yet implemented).
- `dependencies`: dependencies of the target.
- `recommended_files_to_open`: source/test files worth inspecting first.

These fields are locked by `tests/unit/test_tdd_mcp_contract.py`.

## Ownership boundary

TDD MCP owns workflow state (RED, GREEN, REFACTOR, and any later
characterization workflow). Project MCP is factual and read-only.
Project MCP must not start or transition TDD state itself.
