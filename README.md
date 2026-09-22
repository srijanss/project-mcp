# Project MCP

## Purpose

Project MCP is an MCP server that builds and maintains a compact, local
knowledge index of a software repository, so an AI client can look up project
structure, symbols, tests, dependencies, history, and architecture facts
instead of re-reading files on every task. Its goal is to reduce discovery
cost; the client's own filesystem and shell tools still handle raw file access.

> Project MCP provides project facts. It does not make design or architecture decisions.

## Project-agnostic design

The server is not tied to any one repository. It is pointed at a project root
and indexes whatever it finds there. The core schema, analyzer registry, and
context-pack tool contracts are language-neutral; language and framework
support are added as analyzers (see below).

## Supported languages and frameworks

- Python: symbols, imports, static calls, pytest test discovery, dependency
  manifests (`pyproject.toml`, `uv.lock`, `requirements*.txt`).
- Django: framework metadata enrichment.
- JavaScript/TypeScript: generic symbols (functions, classes, methods,
  components), imports, exports. Framework-specific enrichment (React,
  Astro, etc.) is not yet implemented.
- Rust: symbols (modules, structs, enums, traits, functions, impl blocks),
  `use` relationships, trait-implementation relationships, and Cargo
  dependency manifests (`Cargo.toml`, `Cargo.lock`).
- Language-neutral: filesystem discovery, git history, architecture docs,
  legacy signals.

npm dependency manifests and React/Astro framework enrichment are deferred
to post-v1 adapters and are not indexed today.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run project-mcp /path/to/your/project     # stdio MCP server
# or
PROJECT_MCP_ROOT=/path/to/your/project uv run project-mcp
```

Register it in your MCP client as a stdio server running the command above.
Run the tests with `uv run pytest`.

## Project-local `.project-mcp/`

All state lives inside the indexed project, in `.project-mcp/`:

- `.project-mcp/index.db` - the SQLite index.
- `.project-mcp/config.toml` - optional configuration.

Consider adding `.project-mcp/` to the project's `.gitignore`.

### Configuration

`.project-mcp/config.toml` keys: `exclude`, `source_roots`, `test_roots`,
`architecture_docs`, `legacy_paths`, `git_history_limit` (default 100), and
the legacy thresholds `large_file_lines` (500), `large_symbol_lines` (100),
`high_churn_count` (20), `high_fan_in_count` (15), `high_fan_out_count` (15),
`high_temporal_coupling_count` (5). Thresholds must be non-negative integers.

### Default excludes

`.git`, `.venv`, `venv`, `node_modules`, `target`, `dist`, `build`. Files
matching `.env`, `*.pem`, and `*.key` are always excluded. Setting `exclude`
in the config replaces the default list.

## SQLite as a rebuildable index

The SQLite database is a cache derived from the repository, never a source of
truth. It is safe to delete `.project-mcp/index.db` at any time; the next
query rebuilds it with a full scan.

## Indexing lifecycle

- **never_indexed**: first tool call triggers a full scan.
- **fresh**: index matches the filesystem; reads are served directly.
- **stale**: files changed, were added, or were removed since the last index;
  the next tool read triggers an incremental refresh that re-analyzes only
  changed files.
- **indexing**: a scan is in progress.

Tools refresh a stale index automatically before reading. Use
`get_index_status` to inspect state and `refresh_index` to force a refresh.

## Confidence and evidence semantics

Derived facts carry evidence and, where inferred, a confidence level.
Static analysis is best-effort: call and import relationships come from static
parsing and can miss dynamic behavior. Legacy signals include a `confidence`
and a list of `evidence` strings describing exactly what was measured. Treat
low-confidence results as leads to verify, not conclusions.

## Git history limitations

Git-derived tools (`get_change_history`, `get_hotspots`, `get_change_coupling`)
examine only the most recent `git_history_limit` commits (default 100), so
older history is not reflected. Temporal coupling counts files changed in the
same commit and shows co-change, not causation. Projects that are not git
repositories, or shallow clones, yield limited or empty results.

## Legacy-signal semantics

Legacy signals are evidence-backed observations (for example `large_file`,
`large_symbol`, `explicit_legacy_path`, high churn, high fan-in/fan-out,
high temporal coupling), each with a severity, confidence, and evidence. They
are thresholds applied to measurements, not verdicts. They do not say code is
bad or should be rewritten. `get_legacy_signals` and `get_legacy_hotspots`
expose them.

## Architecture: explicit vs derived

Architecture facts are **explicit** when they come from documents the project
wrote itself: `docs/architecture/`, `docs/adr/`, `ADR*.md`, a README
"Architecture" section, or paths listed in `architecture_docs`. Facts
**derived** from code structure (imports, dependencies) are reported
separately and are never presented as documented intent. Use
`get_architecture_facts` and `get_architecture_context`.

## Tools

Project and index:

- `get_project_overview` - languages, roots, manifests, file counts, index status.
- `get_index_status`, `refresh_index` - inspect and refresh the index.

Symbols and relationships:

- `find_symbol`, `get_symbol_context`, `get_dependencies`, `get_dependents`.

Dependencies:

- `list_dependencies`, `get_dependency_version`.

Tests:

- `get_tests_for`, `get_test_summary`.

Git history:

- `get_change_history`, `get_hotspots`, `get_change_coupling`.

Architecture and legacy:

- `get_architecture_facts`, `get_architecture_context`,
  `get_legacy_hotspots`, `get_legacy_signals`.

### Context packs

Context packs bundle the facts most useful for a task type in one call:
`get_context_for_symbol`, `get_context_for_feature`, `get_context_for_bug`,
`get_context_for_refactor`, and `get_context_for_architecture`. Feature and
symbol packs return stable `related_tests`, `entrypoints`, `dependencies`, and
`recommended_files_to_open` fields (see `docs/tdd-mcp-contract.md`).

## Token-saving benchmark approach

`uv run python -m project_mcp.benchmark` compares two approaches on a fixed
fixture corpus of tasks: a naive baseline that opens every plausibly relevant
file, versus a single context-pack call. It reports files opened, bytes, and a
token proxy for each, plus the percentage reduction per task. The token count
is a proxy, not a real tokenizer measurement.

## How to add a new language analyzer

1. Add a package under `project_mcp/analyzers/<language>/` (see
   `project_mcp/analyzers/python/` for the shape).
2. Emit facts in the existing normalized schema; do not change
   `project_mcp/schema.py` or `project_mcp/db.py`.
3. Wire the analyzer into the indexer scan in `project_mcp/indexer.py` for the
   file extensions it owns.
4. Write tests under `tests/unit/` with a fixture project under
   `tests/fixtures/`.

## How to add a framework analyzer

1. Add a module under `project_mcp/analyzers/frameworks/` (see `django.py`).
2. Enrich already-indexed symbols with framework metadata rather than
   re-parsing the language.
3. Call it from the indexer after the language analyzer runs, and cover it
   with fixture-based tests.

## Boundaries with other MCP servers

Project MCP is factual and read-only. It never starts workflows, edits code,
or decides anything.

- **TDD MCP**: owns RED/GREEN/REFACTOR workflow state. Project MCP supplies
  context via `get_context_for_*` (see `docs/tdd-mcp-contract.md`).
- **Design Advisor MCP**: owns design recommendations. Project MCP supplies
  structure, dependency, and legacy-signal facts as input.
- **Architecture MCP**: owns architecture decisions and rules. Project MCP
  supplies explicit architecture docs and derived structure.
- **Playwright MCP**: owns browser automation and UI testing. Project MCP does
  not drive or inspect running apps.
- **AKS MCP**: owns Kubernetes/AKS cluster operations. Project MCP does not
  touch clusters.
- **Deploy MCP**: owns deployment. Project MCP does not build, release, or
  deploy.
