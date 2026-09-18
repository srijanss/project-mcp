# project-mcp — SPEC

Project-agnostic MCP server that builds and maintains a compact, local knowledge index of a software repository so AI coding clients can understand project structure without repeatedly scanning large numbers of files.

The primary goal is to reduce repository-discovery cost, tool calls, spawned exploration agents, and token usage before implementation or review begins.

The Project MCP does **not** replace the coding agent's filesystem, shell, editor, grep, tests, or git tools. It answers higher-level questions such as:

- What is this project?
- How is the code laid out?
- What depends on this module or symbol?
- Which tests are related?
- Which areas appear legacy/high-risk?
- Which files usually change together?
- What architecture has been explicitly declared?
- What compact context should another MCP or AI client receive for a feature, bug, refactor, or architecture discussion?

This spec is split into MVPs so they can be worked on independently by separate agents. Each MVP has its own scope, files, dependencies, and acceptance criteria.

**Read the whole "Shared context" section before starting any MVP.**

---

# Shared context (applies to every MVP)

## Purpose

Project MCP is a **project knowledge/indexing system**, not an advisory system.

It provides facts and derived project knowledge.

Other systems consume that knowledge:

```text
                    AI Client
                 Claude / Codex
                       |
                       v
                  Project MCP
               project facts/index
                       |
        +--------------+---------------+
        |              |               |
        v              v               v
 Design Advisor   Architecture MCP    TDD MCP
 local design     system reasoning    workflow
```

Project MCP should not decide:

- which design pattern should be used
- whether a monolith should become microservices
- whether a refactor is architecturally correct
- what implementation should be written

Those belong to downstream advisory/reasoning systems.

Core principle:

> Do expensive repository discovery once; perform cheap structured retrieval many times.

---

## Primary goals

1. Build a language-neutral knowledge model for a repository.
2. Persist that model in a local per-project SQLite database.
3. Incrementally update the index when project files change.
4. Support Python, JavaScript/TypeScript, and Rust without changing the core schema.
5. Add framework-specific enrichment for Django, React, Astro, and future frameworks through adapters.
6. Capture structural dependencies, test relationships, and selected Git history signals.
7. Distinguish explicit architecture facts from inferred structure.
8. Expose compact context packs for features, bugs, refactors, and architecture/design discussions.
9. Reduce the number of files and tokens an AI agent must consume before it can work effectively.
10. Remain disposable and rebuildable: the repository is always the source of truth, not the SQLite database.

---

## Non-goals

Project MCP is **not**:

- an editor
- a coding agent
- a shell wrapper
- a general filesystem MCP
- a replacement for grep/ripgrep
- a language server
- a vector database
- a semantic code-search product
- a CI/CD tool
- a deployment tool
- a production runtime inspector
- a design-pattern recommender
- an architecture decision engine
- a test runner
- a database browser

---

## Stack

Initial stack:

- Python 3.12+
- `mcp` SDK / `FastMCP`
- `sqlite3` from Python stdlib initially
- `pyyaml`
- `tomllib`
- `ast`
- `pathlib`
- `subprocess` only for narrowly scoped **read-only Git commands**
- stdio transport initially

Parser libraries may be added by language-specific MVPs when justified.

Possible later parser choices:

- Python: stdlib `ast`
- JavaScript/TypeScript: tree-sitter or dedicated JS/TS parser
- Rust: tree-sitter-rust or a Rust-side parser/helper if required

Do not add heavy infrastructure until a concrete analyzer requires it.

---

## Per-project storage

Each analyzed repository gets a local generated state directory:

```text
my-project/
  ...
  .project-mcp/
    config.toml          # optional committed project-specific hints
    index.db             # generated, gitignored
    state.json           # generated index metadata, gitignored
```

Recommended `.gitignore`:

```text
.project-mcp/index.db
.project-mcp/state.json
```

`config.toml` may be committed when the team wants shared project hints.

The SQLite database is:

- derived
- local
- disposable
- rebuildable
- never the source of truth

Deleting `.project-mcp/index.db` and rebuilding must not alter project behavior.

---

## Server repo layout (fixed — don't restructure)

```text
project-mcp/
  main_stdio.py
  requirements.txt

  project_mcp/
    __init__.py

    config.py
    db.py
    schema.py
    indexer.py
    ignore.py

    model/
      __init__.py
      project.py
      file.py
      symbol.py
      relationship.py
      test.py
      git.py
      architecture.py
      context.py

    analyzers/
      __init__.py
      base.py
      registry.py

      generic/
        __init__.py
        filesystem.py

      python/
        __init__.py
        analyzer.py

      javascript/
        __init__.py
        analyzer.py

      rust/
        __init__.py
        analyzer.py

      frameworks/
        __init__.py
        django.py
        react.py
        astro.py

    git/
      __init__.py
      history.py
      churn.py
      coupling.py

    architecture/
      __init__.py
      docs.py
      adr.py
      facts.py

    context/
      __init__.py
      symbol.py
      feature.py
      bug.py
      refactor.py
      architecture.py

    tools/
      __init__.py
      project.py
      symbols.py
      dependencies.py
      tests.py
      legacy.py
      context.py
      index.py

  tests/
    fixtures/
      python/
      django/
      javascript/
      react/
      astro/
      rust/
      git-history/

    unit/
    integration/

  README.md
```

---

## Core design rules

- `main_stdio.py` is the only MCP transport entrypoint.
- Tool functions must remain plain Python functions returning plain dicts.
- MCP-specific decorators/wiring belong only in the transport layer.
- Core analyzers must not depend on Claude-, Codex-, or client-specific behavior.
- Every tool returns a dict containing at least `status`.
- Expected failures return structured errors; do not throw raw exceptions to the client.
- No MCP tool may modify source files.
- No MCP tool may commit, push, merge, deploy, or mutate application state.
- Project MCP may use narrowly scoped read-only Git commands.
- Project MCP must never expose generic `run_shell`, `read_any_file`, or `query_sqlite` tools.
- SQLite is an implementation detail. AI clients must use domain tools, not direct SQL.
- Avoid returning large code bodies. Return paths, symbols, relationships, summaries, evidence, and limitations.
- All derived results should include evidence/source references where practical.
- Distinguish `explicit`, `derived`, and `heuristic` results.
- Never present heuristic analysis as guaranteed truth.
- Ignore generated/vendor directories by default.
- Never index secrets intentionally.
- `.env`, credential files, private keys, build secrets, and known secret locations must be excluded by default.
- The indexing layer must remain language-neutral.
- Framework analyzers enrich the generic model; they do not define the core schema.

---

# Normalized knowledge model

The core schema should remain project/language agnostic.

```text
Project
  |
  +-- Files
  +-- Symbols
  +-- Relationships
  +-- Tests
  +-- Dependencies
  +-- GitFacts
  +-- ArchitectureFacts
  +-- LegacySignals
```

## Files

Suggested fields:

```text
id
path
language
file_kind
size
mtime_ns
content_hash
parser_version
indexed_at
```

`file_kind` examples:

```text
source
test
config
documentation
migration
template
manifest
generated
unknown
```

## Symbols

Suggested fields:

```text
id
file_id
name
qualified_name
kind
language
start_line
end_line
visibility
metadata_json
```

Language-neutral `kind` examples:

```text
module
class
function
method
trait
interface
struct
enum
component
service
model
route_handler
test
unknown
```

Framework analyzers may add metadata without changing the normalized core.

## Relationships

Suggested fields:

```text
id
source_entity_type
source_entity_id
target_entity_type
target_entity_id
relationship_type
confidence
evidence_json
```

Relationship types may include:

```text
contains
imports
uses
calls
inherits
implements
depends_on
tests
routes_to
renders
reads_config
writes_domain_state
changes_with
```

Not every language analyzer must support every relationship type.

## Dependencies

Suggested fields:

```text
name
ecosystem
declared_version
resolved_version
source_file
scope
metadata_json
```

Supported ecosystems initially:

```text
python
npm
cargo
```

## Tests

Tests should be normalized independently of language/framework:

```text
id
symbol_id
file_id
test_kind
framework
metadata_json
```

`test_kind`:

```text
unit
integration
functional
e2e
characterization
unknown
```

## Git facts

Store selected derived data rather than every diff.

Possible facts:

```text
file change count
last changed timestamp
recent churn
files frequently changed together
bugfix-associated churn (later/heuristic)
```

Do not initially store full patch history.

## Architecture facts

Architecture facts must track origin.

Example:

```text
fact:
  subject: payments
  predicate: may_depend_on
  object: shared
  origin: explicit
  source: docs/architecture/payments.md
```

Versus:

```text
fact:
  subject: payments
  predicate: imports
  object: orders
  origin: derived
  source: source dependency graph
```

Never silently treat derived structure as intended architecture.

## Legacy signals

Do not store a single authoritative `legacy = true`.

Store evidence/signals.

Possible signals:

```text
high_churn
high_fan_in
high_fan_out
large_file
large_symbol
circular_dependency
low_test_relationship
many_side_effect_dependencies
frequent_change_coupling
deprecated_dependency
explicit_legacy_path
old_framework_pattern
```

Each signal should have:

```text
target
signal
severity
confidence
evidence
```

The Project MCP reports evidence.

The Design Advisor MCP decides how to reason about it.

---

# Index lifecycle

Project MCP should not rescan an entire repository for every query.

```text
first run
   |
   v
full scan
   |
   v
index.db

later run
   |
   v
detect changed/new/deleted files
   |
   v
re-analyze only affected data
   |
   v
update index.db
```

File-change detection may use:

```text
path
mtime
size
content hash
parser version
```

Correctness matters more than micro-optimization.

A stale index is worse than a slightly slower refresh.

---

# Analyzer model

Analyzers are plugins behind a common interface.

Conceptually:

```text
Analyzer
  detect(...)
  analyze_file(...)
  analyze_project(...)
  relationships(...)
```

Initial analyzers:

```text
GenericFilesystemAnalyzer
PythonAnalyzer
JavaScriptAnalyzer
TypeScriptAnalyzer
RustAnalyzer
DjangoAnalyzer
ReactAnalyzer
AstroAnalyzer
```

Language analyzers extract generic facts.

Framework analyzers enrich those facts.

Examples:

```text
PythonAnalyzer:
  class OrderView
  imports OrderService

DjangoAnalyzer:
  OrderView is a request handler
  /orders/<id> routes to OrderView
```

```text
TypeScriptAnalyzer:
  CheckoutPage imports CheckoutForm

ReactAnalyzer:
  CheckoutPage and CheckoutForm are React components
```

```text
RustAnalyzer:
  StripeProcessor implements PaymentProcessor
```

---

# MCP tool philosophy

Tools should answer semantic project questions.

Good:

```text
get_project_overview()
get_symbol_context(...)
get_dependents(...)
get_tests_for(...)
get_legacy_hotspots(...)
get_context_for_refactor(...)
```

Bad:

```text
read_file(...)
grep(...)
run_shell(...)
query_sql(...)
dump_all_symbols(...)
```

The AI client's existing filesystem/shell tools handle raw access.

Project MCP should reduce discovery cost.

---

# MVP 0 — Skeleton, config, and storage convention

**Depends on:** nothing.

## Scope

Create the server repository layout.

Implement:

```text
project_mcp/config.py
project_mcp/db.py
main_stdio.py
```

Support analyzing a repository passed through config.

Project-local optional configuration:

```text
.project-mcp/config.toml
```

Example:

```toml
exclude = [
  ".git",
  ".venv",
  "node_modules",
  "target",
  "dist",
  "build"
]

source_roots = [
  "src",
  "apps",
  "packages"
]

test_roots = [
  "tests"
]

architecture_docs = [
  "docs/architecture",
  "docs/adr"
]

legacy_paths = [
  "legacy"
]
```

Default excludes must work without configuration.

Create/open:

```text
<target-project>/.project-mcp/index.db
```

## Acceptance criteria

- server starts over stdio
- configured project root is validated
- `.project-mcp/` is created when required
- index database can be created/opened
- target source files remain unchanged
- missing config produces clear startup error
- generated DB can be deleted safely

---

# MVP 1 — SQLite schema and index lifecycle

**Depends on:** MVP 0.

## Scope

Implement normalized SQLite tables for at least:

```text
projects
files
symbols
relationships
dependencies
tests
architecture_facts
legacy_signals
index_metadata
```

Implement DB schema versioning.

Implement index lifecycle helpers:

```text
begin_index()
upsert_file(...)
remove_file(...)
mark_index_complete(...)
get_index_status()
```

Track parser/index schema versions.

## Acceptance criteria

- fresh DB is initialized automatically
- reopening existing DB preserves data
- schema version is recorded
- deleting source file removes stale indexed facts after refresh
- changing parser/index version can invalidate relevant cached data cleanly
- DB contains no project source bodies by default

---

# MVP 2 — Generic filesystem/project index

**Depends on:** MVP 1.

## Scope

Implement generic repository discovery.

Index:

- files
- extensions
- probable language
- source/test/config/docs classification
- project manifests
- common source roots
- common test roots

Exclude:

```text
.git
.venv
venv
node_modules
target
dist
build
coverage
generated/cache paths
secrets/private keys
```

Add tool:

```text
get_project_overview() -> dict
```

Return:

```text
project
languages
source_roots
test_roots
manifests
framework_hints
file_counts
index_status
```

## Acceptance criteria

- works against Python, JS/TS, and Rust fixture projects
- `node_modules`, `.venv`, and `target` are not indexed
- project overview uses SQLite after indexing
- no framework-specific assumptions are required
- second unchanged scan does not fully re-index all files

---

# MVP 3 — Python analyzer

**Depends on:** MVP 2.

## Scope

Use Python AST/static parsing.

Extract:

```text
modules
classes
functions
methods
imports
inheritance
basic call/use relationships where statically clear
```

Do not import or execute target project Python code.

Add/enable generic tools:

```text
find_symbol(query)
get_symbol_context(symbol)
get_dependencies(symbol)
get_dependents(symbol)
```

## Acceptance criteria

- indexes representative Python project
- does not execute project imports
- import relationships are correct for fixtures
- syntax errors in one file do not break whole-project indexing
- dynamic Python behavior is marked as limitation rather than guessed

---

# MVP 4 — JavaScript/TypeScript analyzer

**Depends on:** MVP 2.

## Scope

Parse representative JS/TS projects.

Extract:

```text
modules
functions
classes
components where syntactically detectable
imports
exports
basic dependency relationships
```

Add parser dependency only if needed.

Ignore generated/vendor output.

## Acceptance criteria

- indexes Vanilla JS fixture
- indexes React/TS fixture at generic language level
- detects ES module imports
- does not scan `node_modules`
- dynamic imports/requires are reported conservatively

---

# MVP 5 — Rust analyzer

**Depends on:** MVP 2.

## Scope

Extract:

```text
modules
structs
enums
traits
impl blocks
functions
use relationships
trait implementation relationships
```

Read Cargo manifests/dependencies.

Do not execute `cargo build`.

## Acceptance criteria

- indexes representative Rust crate/workspace
- trait -> implementation relationship is represented
- Cargo dependencies are indexed
- `target/` is ignored
- macro-generated structure is treated conservatively

---

# MVP 6 — Dependency/manifests indexing

**Depends on:** MVP 2.

Can be built in parallel with MVP 3–5.

## Scope

Support:

Python:

```text
pyproject.toml
uv.lock
requirements*.txt
```

JavaScript:

```text
package.json
package-lock.json
pnpm-lock.yaml
yarn.lock (if justified)
```

Rust:

```text
Cargo.toml
Cargo.lock
```

Tools:

```text
list_dependencies(ecosystem: str | None = None)
get_dependency_version(name, ecosystem: str | None = None)
```

Prefer exact/resolved versions from lockfiles.

Return whether a version is:

```text
resolved
declared
unknown
```

## Acceptance criteria

- resolved versions are distinguished from version ranges
- no package manager is executed
- Python/npm/Cargo fixtures work
- unknown dependency returns `not_found`

---

# MVP 7 — Framework enrichment: Django, React, Astro

**Depends on:** relevant language analyzers.

## Scope

### Django

Enrich:

```text
apps
models
routes
views/handlers
migrations
common service/query modules when deterministically discoverable
```

Do not call `django.setup()` or connect to DB.

### React

Enrich:

```text
components
page-level components
component usage relationships
common route declarations where statically visible
```

### Astro

Enrich:

```text
src/pages routing
Astro components
layouts
page/component relationships
```

Framework metadata should map to normalized symbols/relationships.

## Acceptance criteria

- generic language model still works when framework analyzer disabled
- Django project is not executed
- React dynamic patterns are marked partial where needed
- Astro filesystem routes resolve correctly
- framework enrichment does not change the core SQLite schema

---

# MVP 8 — Test relationship index

**Depends on:** MVP 3–5.

## Scope

Index tests and associate them with source targets.

Evidence may include:

```text
direct imports
symbol references
naming conventions
co-located tests
framework test layout
configured test roots
```

Tools:

```text
get_test_summary()
get_tests_for(target)
```

Relationships should include:

```text
relationship
confidence
evidence
```

Do not run tests.

Do not conclude `"untested": true` only because no direct test relationship was found.

## Acceptance criteria

- Python source -> pytest relationship fixture works
- React source -> colocated test fixture works
- Rust source -> test module/integration test relationship works
- E2E is distinct from unit/integration
- absence of evidence is not reported as proof of no testing

---

# MVP 9 — Git history, churn, and temporal coupling

**Depends on:** MVP 2.

Can be developed independently of framework analyzers.

## Scope

Use narrowly scoped read-only Git commands.

Index selected Git facts:

```text
change count per file
last changed date
recent churn
files changed together
```

Initial time window/commit limit should be configurable.

Do not store full diffs in SQLite.

Tools:

```text
get_change_history(path)
get_hotspots()
get_change_coupling(path)
```

Temporal coupling example:

```text
orders/service.py
payments/service.py

changed together in:
31 / 40 recent changes involving orders/service.py
```

Clearly label this as historical correlation, not architectural proof.

## Acceptance criteria

- read-only Git commands only
- repository is unchanged after indexing
- churn fixture gives deterministic expected result
- co-change fixture detects known temporal coupling
- repositories with no Git history still function without failure

---

# MVP 10 — Architecture docs and ADR ingestion

**Depends on:** MVP 2.

## Scope

Index explicit project architecture sources.

Initial sources:

```text
README architecture sections
docs/architecture/
docs/adr/
ADR*.md
configured architecture paths
.project-mcp/config.toml hints
```

Store explicit facts separately from derived source structure.

Tools:

```text
get_architecture_facts()
get_architecture_context(area: str | None = None)
```

Do not ask an LLM to infer arbitrary architecture documents in this MVP.

Simple metadata/heading extraction is enough initially.

## Acceptance criteria

- explicit architecture facts preserve source path
- explicit and derived facts are distinguishable
- missing docs returns valid empty result
- no architecture claim is fabricated from absent documentation

---

# MVP 11 — Legacy signals and hotspot model

**Depends on:** MVP 8 and MVP 9.

Framework enrichment improves quality but is not mandatory.

## Scope

Compute **signals**, not a binary legacy verdict.

Initial signals:

```text
high_churn
high_fan_in
high_fan_out
large_file
large_symbol
circular_dependency
weak_test_relationship
high_temporal_coupling
explicit_legacy_path
```

Tools:

```text
get_legacy_hotspots(limit: int = 20)
get_legacy_signals(target)
```

Each result includes:

```text
signal
severity
confidence
evidence
```

Do not return:

```text
"this code is bad"
"must refactor"
```

Those are Design Advisor concerns.

## Acceptance criteria

- fixture hotspot receives expected signals
- signals are evidence-backed
- no single heuristic silently marks code as legacy
- thresholds are configurable
- explicit project configuration can mark known legacy zones

---

# MVP 12 — Context packs

**Depends on:** MVP 3–11 as applicable.

This is the main token-saving MVP.

## Goal

Allow downstream AI clients/MCPs to obtain one compact project slice instead of exploring dozens of files.

## Tools

```text
get_context_for_symbol(target)
get_context_for_feature(query)
get_context_for_bug(query)
get_context_for_refactor(target)
get_context_for_architecture(area)
```

### Context pack contents

Include only relevant information.

Possible structure:

```text
target
summary

entrypoints
symbols
dependencies
dependents
tests
routes
models/components
related_files

git:
  churn
  temporal_coupling

legacy_signals

architecture:
  explicit_facts
  derived_structure

recommended_files_to_open

limitations
sources
```

`recommended_files_to_open` means:

> These appear most relevant for the coding client to inspect directly.

It is **not** an implementation recommendation.

## Query resolution

For free-text feature/bug queries, start simple.

Use:

- symbol/path/name matches
- route matches
- framework metadata
- dependency relationships
- test names
- documentation names

Do not add embeddings/vector search in this MVP.

If deterministic retrieval is insufficient, return low confidence/limitations.

## Acceptance criteria

- representative feature query returns a compact context slice
- context pack does not dump entire source files
- returned sources are traceable
- result is substantially smaller than reading all related project files
- refactor context includes tests + dependents + churn/legacy evidence when available
- architecture context distinguishes explicit docs from inferred dependency structure

---

# MVP 13 — Incremental refresh and stale-index protection

**Depends on:** MVP 12.

## Scope

Make context retrieval safe for active development.

Before serving project context, Project MCP should cheaply determine whether relevant indexed files may be stale.

Support:

```text
refresh_index()
get_index_status()
```

Possible states:

```text
fresh
stale
refreshing (future)
partial
error
```

Initial implementation may perform refresh synchronously.

Do not introduce background daemons/watchers yet.

## Acceptance criteria

- edited file is re-indexed
- deleted file disappears from relationships
- unchanged files are not reparsed
- context-pack call does not silently serve known-stale data
- index rebuild from scratch produces equivalent normalized facts

---

# MVP 14 — Token-efficiency benchmark

**Depends on:** MVP 12–13.

Token reduction is a product requirement and should be measured.

## Scope

Create a benchmark procedure using several real/fixture tasks.

Example task types:

```text
find where order cancellation belongs
find tests related to payment capture
understand checkout legacy module
identify files relevant to a UI bug
prepare context for architecture discussion
```

Compare:

```text
A. coding agent without Project MCP
B. coding agent with Project MCP context pack
```

Measure where available:

```text
files opened before implementation/reasoning
exploration tool calls
exploration subagents spawned
input tokens
time/tool calls until relevant source identified
```

Project MCP does not need to measure Claude/Codex internally. Manual benchmark capture is acceptable initially.

## Success criterion

The benchmark should demonstrate that Project MCP materially reduces repository exploration for at least the target project classes.

The exact percentage should be learned rather than invented beforehand.

---

# MVP 15 — Integration contract for Design Advisor, Architecture MCP, and TDD MCP

**Depends on:** MVP 12.

Project MCP does not call these systems directly in v1.

Instead define stable context contracts they can consume.

## Design Advisor input

```text
get_context_for_refactor(target)
get_context_for_symbol(target)
```

Expected use:

```text
Project MCP
   |
   v
facts / tests / dependencies / legacy evidence
   |
   v
Design Advisor MCP
   |
   v
refactoring/design discussion
```

Design Advisor remains responsible for:

```text
code smells
design forces
pattern fit
refactoring options
trade-offs
refactoring sequence
```

## Architecture MCP input

```text
get_context_for_architecture(area)
get_architecture_facts()
```

Architecture MCP remains responsible for:

```text
system boundaries
quality attributes
architecture options
trade-offs
failure modes
ADRs/decisions
```

## TDD MCP input

Project MCP may provide:

```text
tests related to target
entrypoints
dependencies
recommended source/test files to inspect
```

TDD MCP remains responsible for workflow state:

```text
RED
GREEN
REFACTOR
characterization workflow if later added
```

Project MCP must not start or transition TDD state itself.

## Acceptance criteria

- context schemas are documented
- downstream clients do not need direct SQLite access
- no circular ownership between MCPs
- Project MCP remains factual/read-only

---

# MVP 16 — README and handoff documentation

**Depends on:** MVP 0–15 as implemented.

## Scope

Document:

- purpose
- project-agnostic design
- SQLite as rebuildable index
- setup
- project-local `.project-mcp/`
- default excludes
- supported languages/frameworks
- indexing lifecycle
- confidence/evidence semantics
- Git-history limitations
- legacy-signal semantics
- architecture explicit-vs-derived distinction
- context-pack tools
- token-saving benchmark approach
- how to add a new language analyzer
- how to add a framework analyzer
- boundaries with:
  - TDD MCP
  - Design Advisor MCP
  - Architecture MCP
  - Playwright MCP
  - AKS MCP
  - Deploy MCP

Explicitly document:

> Project MCP provides project facts. It does not make design or architecture decisions.

## Acceptance criteria

A developer with no prior design context can:

1. install the server
2. point it at a Python, JS/TS, or Rust project
3. build the local index
4. query project context
5. understand confidence/limitations
6. rebuild the index safely

using only the README.

---

# Suggested build order for parallel agents

## Foundation

```text
Agent A -> MVP 0
Agent A -> MVP 1
Agent B -> MVP 2
```

MVP 0–2 should be stabilized before adding language analyzers.

## Language analyzers — parallel

After MVP 2:

```text
Agent C -> MVP 3 Python
Agent D -> MVP 4 JavaScript/TypeScript
Agent E -> MVP 5 Rust
Agent F -> MVP 6 dependencies/manifests
```

## Enrichment — parallel

After relevant analyzer support exists:

```text
Agent G -> MVP 7 framework enrichment
Agent H -> MVP 8 tests
Agent I -> MVP 9 Git history
Agent J -> MVP 10 architecture docs
```

## Intelligence layer

Then:

```text
Agent K -> MVP 11 legacy signals
Agent L -> MVP 12 context packs
Agent A -> MVP 13 incremental refresh
```

## Validation/integration

Finally:

```text
Agent M -> MVP 14 token-efficiency benchmark
Agent N -> MVP 15 downstream MCP contracts
Any agent -> MVP 16 README
```

---

# First practical milestone

Do **not** wait until every analyzer exists.

The first genuinely useful milestone is:

```text
Python/Django or JS/Rust repository
       |
       v
Project MCP index
       |
       +-- files
       +-- symbols
       +-- imports/dependencies
       +-- tests
       |
       v
get_context_for_symbol(...)
       |
       v
small list of files the coding agent should inspect
```

Success means:

> The AI client can identify the correct small working set of source/test files without spawning broad repository-exploration work.

That validates the central hypothesis before building Git analytics, architecture ingestion, legacy scoring, or additional framework adapters.

---

# Long-term target

```text
                            PROJECT MCP

                        MCP query interface
                               |
                               v
                         Context builder
                               |
                               v
                      Normalized project model
                               |
                               v
                         SQLite index.db
                               |
          +--------------------+--------------------+
          |                    |                    |
          v                    v                    v
    Language analyzers      Git analyzer      Explicit knowledge
   Python / JS / Rust      history/churn      ADR/docs/config
          |
          v
   Framework enrichment
 Django / React / Astro
          |
          +-----------------------------------------+
                               |
                               v
                    compact project context
                               |
        +----------------------+----------------------+
        |                      |                      |
        v                      v                      v
 Design Advisor MCP      Architecture MCP         TDD MCP
```

The Project MCP's job ends at providing compact, current, evidence-backed project knowledge.

It should make downstream reasoning cheaper without trying to replace the reasoning itself.
