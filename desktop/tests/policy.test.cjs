'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { isOwnUrl, validateBackupBytes, validateBackupName, validateExportName, EXPORT_LIMIT, validateExternalUrl, validateWorkspace, parseReadyLine } = require('../lib/policy.cjs')

test('workspace onboarding completion accepts only a boolean through the existing narrow policy', () => {
  for (const onboardingDone of [false, true]) assert.deepEqual(validateWorkspace({ onboardingDone }), { onboardingDone })
  for (const onboardingDone of [undefined, null, 'true', 'false', 0, 1, [], {}, new Boolean(true)]) {
    assert.throws(() => validateWorkspace({ onboardingDone }), TypeError)
  }
  assert.throws(() => validateWorkspace({ onboardingDone: true, path: '../escape' }), TypeError)
})

test('workspace project permission accepts only the two app-native modes', () => {
  for (const projectPermission of ['read_only', 'confirm']) assert.deepEqual(validateWorkspace({ projectPermission }), { projectPermission })
  for (const projectPermission of ['full_access', '', null, undefined, true, 1, [], {}]) assert.throws(() => validateWorkspace({ projectPermission }), TypeError)
  assert.ok(require('../lib/policy.cjs').PROJECT_CHANGE_CODES.has('project_change_read_only'))
})

test('conversation export file names are constrained to Markdown and JSON', () => {
  assert.equal(validateExportName('mens-conversation-ab12cd34-20261001-120000.md'),
    'mens-conversation-ab12cd34-20261001-120000.md')
  assert.equal(validateExportName('talk.json'), 'talk.json')
  for (const name of ['../escape.md', '.hidden.md', 'notes.txt', 'report.md.exe', '', `${'x'.repeat(130)}.md`, 'a/b.md']) {
    assert.throws(() => validateExportName(name), TypeError, name)
  }
  assert.equal(validateBackupBytes(new Uint8Array(10), EXPORT_LIMIT), 10)
  assert.throws(() => validateBackupBytes(new Uint8Array(EXPORT_LIMIT + 1), EXPORT_LIMIT), TypeError)
})

test('only the exact loopback origin receives desktop privileges', () => {
  const origin = 'http://127.0.0.1:53212'
  assert.equal(isOwnUrl(`${origin}/api/health`, origin), true)
  for (const url of ['http://127.0.0.1:53213', 'https://127.0.0.1:53212', 'http://127.0.0.1.example:53212',
    'http://user:pass@127.0.0.1:53212', 'file:///C:/secret', 'javascript:alert(1)', 'http://localhost:53212']) {
    assert.equal(isOwnUrl(url, origin), false, url)
  }
  assert.equal(isOwnUrl(origin, null), false)
})

test('workspace IPC cannot write arbitrary keys or invalid values', () => {
  assert.deepEqual(validateWorkspace({ model: 'openai_compatible' }), { model: 'openai_compatible' })
  assert.deepEqual(validateWorkspace({ model: 'qwen3', conversationId: '123-abcd' }), { model: 'qwen3', conversationId: '123-abcd' })
  assert.deepEqual(validateWorkspace({ conversationId: '' }), { conversationId: '' })
  const appearance = { appearance: 'system', accentColor: '#A1b2c3', localModel: 'hf.co/user/model:Q4_K_M' }
  assert.deepEqual(validateWorkspace(appearance), appearance)
  assert.deepEqual(validateWorkspace({ clientId: '7f3a4b2c-9d1e-4f5a-8b6c-0d1e2f3a4b5c' }), { clientId: '7f3a4b2c-9d1e-4f5a-8b6c-0d1e2f3a4b5c' })
  assert.deepEqual(validateWorkspace({ reasoning: 'fast' }), { reasoning: 'fast' })
  assert.deepEqual(validateWorkspace({ reasoning: 'deep' }), { reasoning: 'deep' })
  for (const value of [null, [], 'abc', { model: 'other' }, { filename: '../config' }, { conversationId: '../config' },
    { conversationId: 'a'.repeat(65) }, { conversationId: 12 }, { appearance: 'unknown' }, { accentColor: 'red' },
    { accentColor: '#fff; color:red' }, { accentColor: null }, { localModel: 12 }, { localModel: 'a'.repeat(129) },
    { localModel: 'bad\nmodel' }, { clientId: '' }, { clientId: '../escape' }, { clientId: 'a'.repeat(65) },
    { clientId: 'bad id' }, { clientId: 12 }, { reasoning: 'ultra' }, { reasoning: true }]) assert.throws(() => validateWorkspace(value))
})

test('workspace IPC preserves canonical reasoning levels and legacy preferences', () => {
  for (const reasoning of ['auto', 'low', 'medium', 'high', 'xhigh', 'max', 'fast', 'deep']) {
    assert.deepEqual(validateWorkspace({ reasoning }), { reasoning })
  }
})

test('workspace IPC rejects unknown or non-string reasoning preferences', () => {
  for (const reasoning of ['ultra', 'HIGH', ' low', '', null, undefined, true, 1, [], {}, new String('high')]) {
    assert.throws(() => validateWorkspace({ reasoning }), TypeError, String(reasoning))
  }
})

test('new native and domestic model preferences pass through the narrow workspace policy', () => {
  for (const model of ['openai_responses', 'anthropic', 'gemini', 'zhipu', 'moonshot', 'doubao',
    'siliconflow', 'hunyuan', 'qianfan', 'minimax', 'stepfun', 'spark', 'yi', 'xiaomi', 'zai',
    'xai', 'openrouter', 'groq', 'mistral', 'together', 'fireworks', 'deepinfra', 'cerebras', 'huggingface', 'cohere']) {
    assert.deepEqual(validateWorkspace({ model }), { model })
  }
  for (const model of ['custom-provider', 'gemini/../file', 'responses', 'qwen']) {
    assert.throws(() => validateWorkspace({ model }))
  }
})

test('backup payloads are bounded and file names sanitized', () => {
  assert.equal(validateBackupName('mens-backup-2026-10-01.zip'), 'mens-backup-2026-10-01.zip')
  for (const value of ['', 'a', '.hidden.zip', '../x.zip', 'x.txt', 'a'.repeat(90) + '.zip', 12, null]) {
    assert.throws(() => validateBackupName(value))
  }
  assert.equal(validateBackupBytes(new Uint8Array(16)), 16)
  assert.equal(validateBackupBytes(new ArrayBuffer(1024)), 1024)
  assert.equal(validateBackupBytes(new Uint8Array(16), 32), 16)
  for (const value of [null, 'abc', 12, {}, new Uint8Array(33)]) {
    assert.throws(() => validateBackupBytes(value, value instanceof Uint8Array ? 32 : undefined))
  }
})

test('external links must be plain HTTPS URLs', () => {
  assert.equal(validateExternalUrl('https://example.edu/mens/download'), 'https://example.edu/mens/download')
  assert.equal(validateExternalUrl('https://example.edu:8443/a?b=1#c'), 'https://example.edu:8443/a?b=1#c')
  for (const value of ['http://example.edu/mens', 'file:///C:/Windows/System32/cmd.exe', 'javascript:alert(1)',
    'https://user:secret@example.edu/mens', 'https://', '', 42, null, undefined, `https://example.edu/${'a'.repeat(2100)}`]) {
    assert.throws(() => validateExternalUrl(value), TypeError, String(value))
  }
})

test('startup accepts only a matching nonce and valid loopback port', () => {
  const ready = { event: 'campus-ready', nonce: 'secret', host: '127.0.0.1', port: 53212 }
  assert.deepEqual(parseReadyLine(JSON.stringify(ready), 'secret'), { origin: 'http://127.0.0.1:53212', port: 53212 })
  assert.equal(parseReadyLine('log line', 'secret'), null)
  for (const update of [{ nonce: 'wrong' }, { host: '0.0.0.0' }, { port: 80 }, { port: 65536 }, { port: '53212' }, { event: 'something' }]) {
    assert.equal(parseReadyLine(JSON.stringify({ ...ready, ...update }), 'secret'), null)
  }
})

test('project change arguments allow only exact opaque IDs and explicit actions', () => {
  const { validateProjectChangeArguments, validateProjectId } = require('../lib/policy.cjs')
  assert.deepEqual(validateProjectChangeArguments(['root-a', 'proposal-a', 'apply']), { projectId: 'root-a', subjectId: 'proposal-a', action: 'apply' })
  for (const value of [undefined, null, {}, [], 42, 'a/b', '../root', 'https://evil.example', 'a?b', 'a b', 'a\n', 'a'.repeat(129)]) assert.throws(() => validateProjectId(value))
  for (const args of [['root', 'proposal', 'write'], ['root', 'proposal', { action: 'apply' }], ['root', { path: 'a.ts' }, 'apply'], ['root', 'proposal', 'apply', { text: 'evil' }]]) assert.throws(() => validateProjectChangeArguments(args))
})

function backupMaterial(overrides = {}) {
  return { archive_id: `backup_${'a'.repeat(64)}`, path: 'src/main.ts', summary: 'Original from a backup',
    created_at: '2026-10-31T12:00:00Z', size_bytes: 42, ...overrides }
}

test('project change lists default old-server archives to an empty list', () => {
  const { validateProjectChangeList } = require('../lib/policy.cjs')
  assert.deepEqual(validateProjectChangeList({ available: true, records: [] }, 'root-a'),
    { available: true, records: [], archives: [] })
})

test('backup archive metadata exposes only the five copy-only public fields', () => {
  const { validateProjectChangeList } = require('../lib/policy.cjs')
  const archive = backupMaterial({ root_key: '[1,2]', root_path: 'C:/private', original_base64: 'c2VjcmV0',
    text: 'secret', digest: 'b'.repeat(64), token: 'private', can_revert: true, action: 'revert', state: 'applied' })
  const result = validateProjectChangeList({ available: true, records: [], archives: [archive], token: 'private' }, 'root-a')
  assert.deepEqual(result, { available: true, records: [], archives: [{ archive_id: `backup_${'a'.repeat(64)}`,
    path: 'src/main.ts', summary: 'Original from a backup', created_at: '2026-10-31T12:00:00Z', size_bytes: 42 }] })
  assert.notEqual(result.archives[0], archive)
})

test('backup archive metadata rejects malformed identities, paths, summaries, dates, and sizes', () => {
  const { validateProjectChangeList } = require('../lib/policy.cjs')
  const invalid = [null, [], 'archive',
    ...['recovery-a', `backup_${'A'.repeat(64)}`, `backup_${'a'.repeat(63)}`, `backup_${'a'.repeat(65)}`, 42]
      .map(archive_id => backupMaterial({ archive_id })),
    ...['../secret', '/absolute.ts', 'C:/secret', 'src\\main.ts', 'src//main.ts', 'src/./main.ts', 'src/\u202emain.ts', '', 'a'.repeat(2049)]
      .map(path => backupMaterial({ path })),
    ...['a'.repeat(801), '\ud800', null].map(summary => backupMaterial({ summary })),
    ...['not-a-date', '', 'a'.repeat(65), 42, null].map(created_at => backupMaterial({ created_at })),
    ...[-1, 65537, 1.5, '42', null, undefined, NaN, Infinity].map(size_bytes => backupMaterial({ size_bytes })),
  ]
  for (const archive of invalid) {
    assert.throws(() => validateProjectChangeList({ available: true, records: [], archives: [archive] }, 'root-a'), TypeError)
  }
  for (const archives of [null, {}, 'archives']) {
    assert.throws(() => validateProjectChangeList({ available: true, records: [], archives }, 'root-a'), TypeError)
  }
})

test('backup archive lists enforce unique IDs and the 256-record bound without rejecting valid limits', () => {
  const { validateProjectChangeList } = require('../lib/policy.cjs')
  const archives = Array.from({ length: 256 }, (_, index) => backupMaterial({
    archive_id: `backup_${index.toString(16).padStart(64, '0')}`, size_bytes: index === 0 ? 0 : 65536,
    summary: '😀'.repeat(800),
  }))
  assert.equal(validateProjectChangeList({ available: true, records: [], archives }, 'root-a').archives.length, 256)
  for (const invalid of [[backupMaterial(), backupMaterial()], [...archives, backupMaterial()]]) {
    assert.throws(() => validateProjectChangeList({ available: true, records: [], archives: invalid }, 'root-a'), TypeError)
  }
})
