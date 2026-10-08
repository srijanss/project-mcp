# Project instructions

## Workflow (all coding agents)

- Read and follow the relevant `.agents/skills/<name>/SKILL.md` before
  starting its workflow. Follow its referenced docs; don't preload unrelated skills.
- Consult project-mcp before source exploration and each TDD decision point.
  Use relevant symbols, dependents and tests rather than large blind searches.
- Run project tests through outside-in-tdd `run_tests()`, not a shell test runner.
  Exception: `node --test .pi/tests/*.test.mjs` tests the Pi hook adapter and
  scaffold offline without touching the shared TDD feature state.
- Await phase-dependent operations sequentially (including inside codemode).
  Inspect each tool result for errors and the current phase before advancing.
  Never run a file edit concurrently with its test or phase transition.
- Keep progress updates to meaningful milestones. Return concise, filtered tool
  results rather than dumping whole files, registries or diffs unnecessarily.
- Respect the shared `.agents/hooks/` protections. Pi adapts the project's
  `.claude/settings.json` hooks through `.pi/extensions/workflow-hooks/`.

## Independent reviews

- Prefer a fresh review session on another model; keep the implementation
  session on its original model. Don't clone/fork the full history for a review.
- Supply the commit range or file scope, requested review categories, and the
  shared findings scope. Consult `list_review_findings(scope)` before rescanning,
  and persist candidates/confirmed findings with `record_review_finding`.
- Bring findings back through the shared store, not the review transcript.
- If the requested review subagent is unavailable, say so and ask before
  substituting a manual review. Use `.claude/agents/review-finder.md` and
  `review-verifier.md` as role guidance in separate sessions when appropriate.

## Git

- Do not push or create branches autonomously. Commit only when requested.
