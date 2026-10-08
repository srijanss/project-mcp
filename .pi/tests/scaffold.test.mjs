import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { basename, join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const hasMcpctl = spawnSync('mcpctl', ['--version']).status === 0;

test('mcpctl init copies Pi assets, merges configs, excludes tests and is idempotent', { skip: !hasMcpctl }, async t => {
  const temp = await mkdtemp(join(tmpdir(), 'pi-scaffold-test-'));
  t.after(() => rm(temp, { recursive: true, force: true }));
  const home = join(temp, 'state');
  const manifest = await readFile(join(root, 'mcpctl.toml'), 'utf8');
  const version = manifest.match(/^version = "([^"]+)"/m)[1];
  const source = join(home, 'packages/project-mcp', version, 'source');
  const target = join(temp, 'consumer');
  await mkdir(source, { recursive: true });
  // Build an installed-source fixture, without installing a runtime or changing real state.
  const paths = new Set(['mcpctl.toml', '.pi', '.claude/commands',
    ...[...manifest.matchAll(/^from = "([^"]+)"/gm)].map(match => match[1])]);
  for (const path of paths) {
    await mkdir(join(source, path, '..'), { recursive: true });
    await cp(join(root, path), join(source, path), { recursive: true, verbatimSymlinks: true });
  }
  await mkdir(join(source, '.pi/tests'), { recursive: true });
  await writeFile(join(source, '.pi/tests/must-not-ship.txt'), 'excluded');
  await writeFile(join(source, '.pi/mcp.json'), JSON.stringify({
    mcpServers: { 'checkout-only': { command: 'uv', args: ['run', 'local-server'] } },
  }));
  await writeFile(join(home, 'registry.json'), JSON.stringify({
    schema_version: 1,
    packages: { 'project-mcp': { active_version: version,
      versions: [{ version, runtime: 'python', source, installed_at: '2026-01-01T00:00:00Z' }] } },
  }));
  await mkdir(join(target, '.pi'), { recursive: true });
  await writeFile(join(target, '.pi/mcp.json'), JSON.stringify({
    mcpServers: { custom: { command: 'custom-server' } },
  }));
  const model = 'claude-bridge/claude-opus-5-5';
  await writeFile(join(target, '.pi/settings.json'), JSON.stringify({
    defaultThinkingLevel: 'low',
    compaction: { modelOverrides: { [model]: { reserveTokens: 900000 } } },
  }));
  const init = () => {
    const result = spawnSync('mcpctl', ['init', 'project-mcp', target], {
      encoding: 'utf8', env: { ...process.env, MCPCTL_HOME: home },
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
  };
  init();
  const mcp = JSON.parse(await readFile(join(target, '.pi/mcp.json'), 'utf8'));
  assert.equal(mcp.mcpServers.custom.command, 'custom-server');
  assert.equal(basename(mcp.mcpServers['project-mcp'].command), 'mcpctl');
  assert.deepEqual(mcp.mcpServers['project-mcp'].args, ['run', 'project-mcp']);
  assert.equal(mcp.mcpServers['checkout-only'], undefined); // checkout-only config isn't copied
  const settings = JSON.parse(await readFile(join(target, '.pi/settings.json'), 'utf8'));
  assert.equal(settings.defaultThinkingLevel, 'low');
  assert.equal(settings.compaction.modelOverrides[model].reserveTokens, 900000);
  assert.equal(settings.compaction.modelOverrides['claude-bridge/claude-sonnet-5-5'].reserveTokens, 850000);
  assert.equal(settings.compaction.keepRecentTokens, 20000);
  assert.match(await readFile(join(target, '.pi/extensions/workflow-hooks/index.js'), 'utf8'), /workflowHooks/);
  assert.match(await readFile(join(target, '.pi/extensions/workflow-hooks/core.mjs'), 'utf8'), /runHooks/);
  assert.match(await readFile(join(target, '.pi/prompts/tdd-start.md'), 'utf8'), /\.agents\/skills\/tdd-start/);
  assert.ok((await readdir(join(target, '.pi'))).includes('README.md'));
  await assert.rejects(readFile(join(target, '.pi/mcp.json.example')), { code: 'ENOENT' });
  await assert.rejects(readdir(join(target, '.pi/tests')), { code: 'ENOENT' });
  const before = await readFile(join(target, '.pi/settings.json'), 'utf8');
  init();
  assert.equal(await readFile(join(target, '.pi/settings.json'), 'utf8'), before);
  assert.deepEqual(JSON.parse(await readFile(join(target, '.pi/mcp.json'), 'utf8')), mcp);
});
