import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import extension from '../extensions/workflow-hooks/index.js';
import { createWorkflowGuard, hookInput, runHooks, scratchpadFor } from '../extensions/workflow-hooks/core.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const event = (toolName, input = {}, extra = {}) => ({ toolName, input, toolCallId: 'call', ...extra });
async function scratch(t) {
  const dir = await mkdtemp(join(tmpdir(), 'pi-hooks-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}
const consult = (dir, e = event('mcp__project_mcp__get_project_overview', {}, { isError: false })) =>
  runHooks('PostToolUse', e, root, dir);

test('maps Pi paths and MCP names to existing Claude hook input', () => {
  const input = hookInput(event('edit', { path: '.env' }), root, '/tmp/test');
  assert.equal(input.tool_name, 'Edit');
  assert.equal(input.tool_input.file_path, '.env');
  assert.equal(hookInput(event('mcp__outside_in_tdd__write_test'), root, '').tool_name,
    'mcp__outside-in-tdd__write_test');
  assert.equal(hookInput(event('mcp__project_mcp__find_symbol'), root, '').tool_name,
    'mcp__project-mcp__find_symbol');
});

test('blocks cold reads and searches, allows docs, unblocks after consultation', async t => {
  const dir = await scratch(t);
  for (const e of [event('read', { path: 'project_mcp/indexer.py' }), event('read', { path: 'plugin.ts' }), event('bash', { command: 'rg parser project_mcp' }), event('grep'), event('find')]) {
    assert.equal((await runHooks('PreToolUse', e, root, dir)).block, true);
  }
  assert.equal(await runHooks('PreToolUse', event('read', { path: 'README.md' }), root, dir), undefined);
  await consult(dir);
  assert.equal(await runHooks('PreToolUse', event('read', { path: 'project_mcp/indexer.py' }), root, dir), undefined);
});

test('a fresh consultation is consumed at each TDD decision; stale markers fail', async t => {
  const dir = await scratch(t);
  const e = event('mcp__outside_in_tdd__write_test');
  assert.equal((await runHooks('PreToolUse', e, root, dir)).block, true);
  await consult(dir);
  assert.equal(await runHooks('PreToolUse', e, root, dir), undefined);
  assert.equal((await runHooks('PreToolUse', e, root, dir)).block, true);
  await writeFile(join(dir, '.project-mcp-consulted'), `${Math.floor(Date.now() / 1000) - 121}`);
  assert.equal((await runHooks('PreToolUse', e, root, dir)).block, true);
});

for (const command of ['pytest -q', '.venv/bin/python -m pytest -q', 'uv run pytest', 'cd /tmp && /usr/bin/python3 -m unittest', 'uv run --quiet python -m pytest', 'npx vitest']) {
  test(`blocks direct tests: ${command}`, async t => {
    assert.equal((await runHooks('PreToolUse', event('bash', { command }), root, await scratch(t))).block, true);
  });
}

test('allows TDD run_tests and harmless shell commands', async t => {
  const dir = await scratch(t);
  for (const e of [event('mcp__outside_in_tdd__run_tests'), event('bash', { command: 'git status --short' })]) {
    assert.equal(await runHooks('PreToolUse', e, root, dir), undefined);
  }
});

test('blocks dangerous commands and protected writes, allows templates', async t => {
  const dir = await scratch(t);
  for (const e of [event('bash', { command: 'git push origin main' }), event('bash', { command: 'rm -rf /tmp/foo' }), event('bash', { command: 'echo secret > .env' }), event('edit', { path: '.env' }), event('write', { path: 'deploy/app.yaml' })]) {
    assert.equal((await runHooks('PreToolUse', e, root, dir)).block, true);
  }
  assert.equal(await runHooks('PreToolUse', event('write', { path: '.env.example' }), root, dir), undefined);
});

test('failed project-mcp calls do not grant consultation; nested successful calls do', async t => {
  const dir = await scratch(t);
  const guard = createWorkflowGuard();
  await guard.after(event('mcp__project_mcp__find_symbol', {}, { isError: true }), root, dir);
  await guard.after(event('mcp__project_mcp__find_symbol', {}, { content: [{ type: 'text', text: '{"isError":true}' }] }), root, dir);
  assert.equal((await guard.before(event('read', { path: 'a.py' }), root, dir)).block, true);
  await guard.after(event('mcp__project_mcp__find_symbol', {}, { parentToolCallId: 'codemode', isError: false }), root, dir);
  assert.equal(await guard.before(event('read', { path: 'a.py', parentToolCallId: 'codemode' }), root, dir), undefined);
});

test('parallel nested TDD mutations are blocked until the first finishes', async t => {
  const dir = await scratch(t);
  const guard = createWorkflowGuard();
  const first = event('mcp__outside_in_tdd__run_tests', {}, { toolCallId: 'parent/1', parentToolCallId: 'parent' });
  const second = event('mcp__outside_in_tdd__verify', {}, { toolCallId: 'parent/2', parentToolCallId: 'parent' });
  const results = await Promise.all([guard.before(first, root, dir), guard.before(second, root, dir)]);
  assert.equal(results[0], undefined);
  assert.match(results[1].reason, /still running/);
  await guard.after({ ...first, isError: true }, root, dir);
  assert.equal(await guard.before(second, root, dir), undefined);
  guard.ended(second, dir);
  assert.equal(await guard.before(first, root, dir), undefined);
});

test('scratchpads isolate projects and sessions and survive reload', () => {
  assert.equal(scratchpadFor(root, 'a'), scratchpadFor(root, 'a'));
  assert.notEqual(scratchpadFor(root, 'a'), scratchpadFor(root, 'b'));
  assert.notEqual(scratchpadFor(root, 'a'), scratchpadFor('/other', 'a'));
});

test('hook failures and invalid configuration fail closed', async t => {
  await assert.rejects(runHooks('PreToolUse', event('bash'), await scratch(t), await scratch(t)));
  const dir = await scratch(t);
  await writeFile(join(dir, '.project-mcp-consulted'), 'bad timestamp');
  assert.equal((await runHooks('PreToolUse', event('mcp__outside_in_tdd__init_feature'), root, dir)).block, true);
});

test('hook timeouts and malformed output cannot grant permission', async t => {
  const cwd = await scratch(t);
  await mkdir(join(cwd, '.claude'));
  const settings = command => writeFile(join(cwd, '.claude/settings.json'), JSON.stringify({
    hooks: { PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command }] }] },
  }));
  await settings('sleep 10');
  await assert.rejects(runHooks('PreToolUse', event('bash'), cwd, await scratch(t), 30), /timed out/);
  await settings('printf not-json');
  await assert.rejects(runHooks('PreToolUse', event('bash'), cwd, await scratch(t)));
});

test('extension registers real tool pipeline handlers (including nested calls)', async t => {
  const handlers = {};
  extension({ on(name, handler) { handlers[name] = handler; } });
  const sessionId = `test-${Date.now()}`;
  const dir = scratchpadFor(root, sessionId);
  t.after(() => rm(dir, { recursive: true, force: true }));
  const ctx = { cwd: root, sessionManager: { getSessionId: () => sessionId } };
  const result = await handlers.tool_call(event('write', { path: '.env' }, { parentToolCallId: 'codemode' }), ctx);
  assert.equal(result.block, true);
  assert.equal(typeof handlers.tool_execution_end, 'function');
});

test('project prompt wrappers preserve every Claude command without duplicating skills', async () => {
  const names = (await readdir(join(root, '.claude/commands'))).filter(n => n.endsWith('.md'));
  for (const name of names) {
    assert.equal(await readFile(join(root, '.pi/prompts', name), 'utf8'), await readFile(join(root, '.claude/commands', name), 'utf8'));
  }
});

test('Claude compaction overrides leave other models and thinking settings alone', async () => {
  const settings = JSON.parse(await readFile(join(root, '.pi/settings.json'), 'utf8'));
  assert.equal(settings.defaultThinkingLevel, undefined);
  assert.equal(settings.compaction.keepRecentTokens, 20000);
  const overrides = settings.compaction.modelOverrides;
  assert.equal(Object.keys(overrides).length, 2);
  for (const [key, value] of Object.entries(overrides)) {
    assert.match(key, /^claude-bridge\//);
    assert.equal(1000000 - value.reserveTokens, 150000);
  }
});
