'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const vm = require('node:vm')

function preparation(projectId, subjectId, action) {
  return { project_id: projectId, subject_id: subjectId, proposal_id: action === 'apply' ? subjectId : 'proposal-a', action,
    digest: 'a'.repeat(64), path: 'src/main.ts', summary: 'Model explanation fixture', added_lines: 2, removed_lines: 1,
    expected_sha256: 'b'.repeat(64), target_sha256: 'c'.repeat(64) }
}
function receipt(projectId, body) {
  return { operation_id: body.operation_id, project_id: projectId, subject_id: body.subject_id,
    proposal_id: body.action === 'apply' ? body.subject_id : 'proposal-a', recovery_id: body.action === 'apply' ? 'recovery-a' : body.subject_id,
    action: body.action, digest: body.digest, state: { apply: 'applied', revert: 'reverted', keep: 'kept' }[body.action],
    path: 'src/main.ts', summary: 'Model explanation fixture', created_at: '2026-10-31T12:00:00Z', can_revert: body.action === 'apply' }
}
async function fixture(t, savedPermission) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'campus-change-main-'))
  const handlers = new Map(); const requests = {}; const prepares = []; const commits = []; const checks = []; const dialogs = []
  let activeWindow; let startup; let userData = temporary; let latest
  const behavior = { confirm: { response: 0 }, confirmHook: async () => {}, prepare: null, commit: null, status: null, list: null, original: null, workspaceWriteFails: false }
  const app = new EventEmitter()
  Object.assign(app, {
    setName() {}, setAppUserModelId() {}, setPath(_key, value) { userData = value },
    getPath(key) { return key === 'appData' ? temporary : userData }, getVersion() { return 'test' }, requestSingleInstanceLock() { return true },
    isPackaged: true, whenReady() { return { then(callback) { startup = Promise.resolve().then(callback); return startup } } }, quit() {}, relaunch() {},
  })
  class BrowserWindow extends EventEmitter {
    constructor() {
      super(); activeWindow = this; this.webContents = new EventEmitter(); this.webContents.id = 17; this.webContents.mainFrame = { url: '' }
      const session = new EventEmitter()
      session.webRequest = { onBeforeRequest(cb) { requests.before = cb }, onBeforeSendHeaders(cb) { requests.headers = cb }, onHeadersReceived() {} }
      session.setPermissionRequestHandler = () => {}; session.setPermissionCheckHandler = () => {}
      this.webContents.session = session; this.webContents.setWindowOpenHandler = () => {}
    }
    async loadURL(url) { this.webContents.mainFrame.url = url }
    show() {} focus() {} isMinimized() { return false } restore() {} isDestroyed() { return false }
    getBounds() { return { width: 1200, height: 800, x: 0, y: 0 } } isMaximized() { return false }
  }
  const backend = {
    ready: Promise.resolve({ origin: 'http://127.0.0.1:53321', token: 'desktop-secret' }), async stop() {},
    async openProject() { return { available: true, changes_available: true, project: { id: 'root-a', name: 'Fixture project' }, limits: { max_files: 4, max_context_chars: 16000 } } },
    async prepareProjectChange(projectId, subjectId, action) { prepares.push([projectId, subjectId, action]); return behavior.prepare ? behavior.prepare(projectId, subjectId, action) : preparation(projectId, subjectId, action) },
    async commitProjectChange(projectId, body) { commits.push([projectId, body]); latest = behavior.commit ? await behavior.commit(projectId, body) : receipt(projectId, body); return latest },
    async projectChangeStatus(projectId, operationId) { checks.push([projectId, operationId]); return behavior.status ? behavior.status(projectId, operationId) : latest },
    async projectChanges(projectId) { return behavior.list ? behavior.list(projectId) : { available: true, records: latest ? [latest] : [] } },
    async projectRecoveryOriginal(...args) { return behavior.original ? behavior.original(...args) : { text: 'original fixture\r\n', bom: true, newline: 'crlf', hidden: 'must not leak' } },
  }
  const directory = path.resolve(__dirname, '..')
  if (savedPermission !== undefined) {
    fs.mkdirSync(path.join(temporary, 'CampusAgent'), { recursive: true })
    fs.writeFileSync(path.join(temporary, 'CampusAgent', 'workspace.json'), JSON.stringify({ clientId: 'fixture-client', projectPermission: savedPermission }))
  }
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'main.cjs'), 'utf8'), {
    require(name) {
      if (name === 'node:fs') return { ...fs, writeFileSync(file, ...args) {
        if (behavior.workspaceWriteFails && file === path.join(temporary, 'CampusAgent', 'workspace.json.tmp')) throw new Error('synthetic workspace disk failure')
        return fs.writeFileSync(file, ...args)
      } }
      if (name === 'electron') return {
        app, BrowserWindow, nativeTheme: { shouldUseDarkColors: false }, screen: { getAllDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] },
        ipcMain: { handle(name, handler) { handlers.set(name, handler) } }, Menu: { buildFromTemplate(value) { return value }, setApplicationMenu() {} }, shell: {},
        dialog: { showErrorBox(_title, message) { throw new Error(message) },
          async showMessageBox(_window, options) { dialogs.push(options); await behavior.confirmHook(); return behavior.confirm },
          async showOpenDialog() { return { canceled: false, filePaths: [path.join(temporary, 'project')] } },
        },
      }
      if (name === './lib/backend.cjs') return { startBackend: () => backend }
      return name.startsWith('.') ? require(path.join(directory, name)) : require(name)
    }, __dirname: directory, process: { platform: 'win32', resourcesPath: temporary }, setTimeout, clearTimeout, TextDecoder,
  }, { filename: 'desktop/main.cjs' })
  await startup
  t.after(() => {
    assert.ok(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep))
    assert.ok(path.basename(temporary).startsWith('campus-change-main-'))
    fs.rmSync(temporary, { recursive: true, force: true })
  })
  const event = { sender: activeWindow.webContents, senderFrame: activeWindow.webContents.mainFrame }
  return { handlers, event, web: activeWindow.webContents, behavior, prepares, commits, checks, dialogs, requests }
}

test('native cancellation obtains immutable metadata but never submits a write', async t => {
  const f = await fixture(t)
  assert.equal(typeof f.handlers.get('campus:change-project-file'), 'function')
  const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
  assert.equal(result.state, 'cancelled'); assert.equal(result.subject_id, 'proposal-a'); assert.equal(result.path, 'src/main.ts')
  assert.match(result.operation_id, /^[a-f0-9-]{36}$/)
  assert.equal(f.commits.length, 0)
  assert.equal(f.dialogs[0].defaultId, 0); assert.equal(f.dialogs[0].cancelId, 0)
  assert.ok(f.dialogs[0].detail.includes('Model explanation fixture'))
  assert.equal('digest' in result, false)
})

test('read-only rejects all mutations before prepare while status and original reads remain usable', async t => {
  const f = await fixture(t)
  f.handlers.get('campus:set-project-permission')(f.event, 'read_only')
  for (const action of ['apply', 'revert', 'keep']) {
    const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', action === 'apply' ? 'proposal-a' : 'recovery-a', action)
    assert.equal(result.error_code, 'project_change_read_only'); assert.equal(result.state, 'failed')
  }
  assert.equal(f.prepares.length, 0); assert.equal(f.dialogs.length, 0); assert.equal(f.commits.length, 0)
  assert.equal((await f.handlers.get('campus:project-changes')(f.event, 'root-a')).available, true)
  assert.equal((await f.handlers.get('campus:project-recovery-original')(f.event, 'root-a', 'recovery-a')).text, 'original fixture\r\n')
  f.behavior.status = (projectId, operationId) => receipt(projectId, { operation_id: operationId, subject_id: 'proposal-a', action: 'apply', digest: 'a'.repeat(64) })
  assert.equal((await f.handlers.get('campus:project-change-status')(f.event, 'root-a', 'operation-a')).state, 'applied')
  assert.equal(f.commits.length, 0)
})

test('read-only revocation survives disk failure and stale workspace snapshots during awaited operations', async t => {
  for (const phase of ['prepare', 'confirm']) {
    const f = await fixture(t); f.behavior.confirm = { response: 1 }
    const stale = f.handlers.get('campus:load-workspace')(f.event)
    const revoke = () => {
      f.behavior.workspaceWriteFails = true
      const result = f.handlers.get('campus:set-project-permission')(f.event, 'read_only')
      assert.equal(result.projectPermission, 'read_only'); assert.equal(result.persisted, false)
      assert.equal(f.handlers.get('campus:load-workspace')(f.event).projectPermission, 'read_only')
      f.behavior.workspaceWriteFails = false
      f.handlers.get('campus:save-workspace')(f.event, stale)
      assert.equal(f.handlers.get('campus:load-workspace')(f.event).projectPermission, 'read_only')
    }
    if (phase === 'prepare') f.behavior.prepare = async (...args) => { await Promise.resolve(); revoke(); return preparation(...args) }
    else f.behavior.confirmHook = async () => { await Promise.resolve(); revoke() }
    const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
    assert.equal(result.error_code, 'project_change_read_only'); assert.equal(f.commits.length, 0)
  }
})

test('permission promotion requires successful persistence and the narrow setter validates sender and mode', async t => {
  const f = await fixture(t, 'read_only')
  const set = f.handlers.get('campus:set-project-permission')
  assert.equal(typeof set, 'function')
  for (const mode of ['', 'full_access', null, undefined, true, 1, [], {}]) assert.throws(() => set(f.event, mode))
  assert.throws(() => set({ sender: {}, senderFrame: f.web.mainFrame }, 'confirm'))
  f.behavior.workspaceWriteFails = true
  const rejected = set(f.event, 'confirm')
  assert.equal(rejected.persisted, false); assert.equal(rejected.projectPermission, 'read_only')
  assert.equal(f.handlers.get('campus:load-workspace')(f.event).projectPermission, 'read_only')
  f.behavior.workspaceWriteFails = false
  const accepted = set(f.event, 'confirm')
  assert.equal(accepted.persisted, true); assert.equal(accepted.projectPermission, 'confirm')
  f.behavior.workspaceWriteFails = true
  assert.equal(set(f.event, 'confirm').projectPermission, 'read_only')
  assert.equal(f.handlers.get('campus:load-workspace')(f.event).projectPermission, 'read_only')
})

test('desktop permission migration, persistence and strict IPC preserve the native-confirmed default', async t => {
  for (const saved of [undefined, 'legacy-unknown', null, 'confirm', 'read_only']) {
    const f = await fixture(t, saved)
    const load = f.handlers.get('campus:load-workspace'); const save = f.handlers.get('campus:save-workspace')
    assert.equal(load(f.event).projectPermission, saved === 'read_only' ? 'read_only' : 'confirm')
    f.handlers.get('campus:set-project-permission')(f.event, 'read_only')
    for (const projectPermission of ['full_access', '', null, undefined, true, 1, [], {}]) {
      assert.throws(() => save(f.event, { projectPermission }))
      assert.equal(load(f.event).projectPermission, 'read_only')
    }
    f.handlers.get('campus:set-project-permission')(f.event, 'confirm'); assert.equal(load(f.event).projectPermission, 'confirm')
    // Returning to confirm still cannot skip the native dialog.
    const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
    assert.equal(result.state, 'cancelled'); assert.equal(f.dialogs.length, 1); assert.equal(f.commits.length, 0)
  }
})

test('switching to read-only during preparation or native confirmation revokes every commit', async t => {
  for (const phase of ['prepare', 'confirm']) for (const action of ['apply', 'revert', 'keep']) {
    const f = await fixture(t); f.behavior.confirm = { response: 1 }
    const revoke = () => f.handlers.get('campus:set-project-permission')(f.event, 'read_only')
    if (phase === 'prepare') f.behavior.prepare = async (...args) => { await Promise.resolve(); revoke(); return preparation(...args) }
    else f.behavior.confirmHook = async () => { await Promise.resolve(); revoke() }
    const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', action === 'apply' ? 'proposal-a' : 'recovery-a', action)
    assert.equal(result.error_code, 'project_change_read_only'); assert.equal(f.commits.length, 0)
    assert.equal(f.dialogs.length, phase === 'prepare' ? 0 : 1)
  }
})

for (const action of ['apply', 'revert', 'keep']) test(`native ${action} commits fixed prepared IDs once and verifies its receipt`, async t => {
  const f = await fixture(t); f.behavior.confirm = { response: 1 }
  const subject = action === 'apply' ? 'proposal-a' : 'recovery-a'
  const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', subject, action)
  assert.equal(result.state, { apply: 'applied', revert: 'reverted', keep: 'kept' }[action])
  assert.equal(f.commits.length, 1); assert.equal(f.checks.length, 1)
  assert.equal(f.commits[0][0], 'root-a')
  assert.deepEqual(Object.keys(f.commits[0][1]).sort(), ['action', 'digest', 'operation_id', 'subject_id'])
  assert.equal(f.commits[0][1].subject_id, subject); assert.equal(f.commits[0][1].digest, 'a'.repeat(64))
  assert.equal(f.checks[0][1], result.operation_id)
  assert.equal('digest' in result, false)
  if (action === 'keep') assert.ok(f.dialogs[0].detail.includes('一键'))
  else {
    assert.ok(f.dialogs[0].detail.includes('原始内容保存在本机恢复记录中'))
    assert.ok(f.dialogs[0].detail.includes('普通本地 NTFS'))
    assert.ok(f.dialogs[0].detail.includes('owner/group/DACL'))
    assert.ok(f.dialogs[0].detail.includes('SACL'))
    assert.equal(f.dialogs[0].detail.includes('不会创建、删除'), false)
  }
  if (action === 'apply') assert.ok(f.dialogs[0].detail.includes('临时副本'))
})

test('sender replacement during confirmation or prepare revokes the call before commit', async t => {
  for (const phase of ['prepare', 'confirm']) {
    const f = await fixture(t); f.behavior.confirm = { response: 1 }
    const replace = () => { f.web.mainFrame = { url: 'http://127.0.0.1:53321' } }
    if (phase === 'prepare') f.behavior.prepare = (...args) => { replace(); return preparation(...args) }
    else f.behavior.confirmHook = async () => replace()
    await assert.rejects(f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply'), /project_change_sender/)
    assert.equal(f.commits.length, 0)
  }
})

test('malicious arguments and duplicate concurrent actions never reach a second confirmation', async t => {
  const f = await fixture(t)
  const change = f.handlers.get('campus:change-project-file')
  for (const args of [['root/a', 'proposal-a', 'apply'], ['root-a', { path: '/etc/passwd' }, 'apply'], ['root-a', 'proposal-a', 'write'], ['root-a', 'proposal-a', 'apply', { digest: 'renderer' }]]) {
    await assert.rejects(change(f.event, ...args), /project_change_invalid_arguments/)
  }
  let release
  f.behavior.confirmHook = () => new Promise(resolve => { release = resolve })
  const first = change(f.event, 'root-a', 'proposal-a', 'apply')
  await new Promise(resolve => setImmediate(resolve))
  const duplicate = await change(f.event, 'root-a', 'proposal-a', 'apply')
  assert.equal(duplicate.error_code, 'project_change_busy'); assert.equal(f.dialogs.length, 1)
  await assert.rejects(f.handlers.get('campus:pick-project')(f.event), /project_change_busy/)
  release(); await first; assert.equal(f.commits.length, 0)
})

test('transport failure, wrong digest, or wrong operation produce uncertainty and never retry commit', async t => {
  for (const mode of ['transport', 'digest', 'operation']) {
    const f = await fixture(t); f.behavior.confirm = { response: 1 }
    f.behavior.commit = (projectId, body) => {
      if (mode === 'transport') throw Object.assign(new Error('C:/private-root token-secret'), { code: 'project_change_transport', status: 0 })
      return { ...receipt(projectId, body), ...(mode === 'digest' ? { digest: 'd'.repeat(64) } : { operation_id: 'wrong-operation' }) }
    }
    const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
    assert.equal(result.state, 'uncertain'); assert.equal(f.commits.length, 1)
    assert.equal(JSON.stringify(result).includes('private-root'), false)
    f.behavior.status = (projectId, operationId) => receipt(projectId, { ...f.commits[0][1], operation_id: operationId, digest: 'e'.repeat(64) })
    await assert.rejects(f.handlers.get('campus:project-change-status')(f.event, 'root-a', result.operation_id), /project_change_invalid_response/)
    f.behavior.status = (projectId, operationId) => receipt(projectId, { ...f.commits[0][1], operation_id: operationId })
    const resolved = await f.handlers.get('campus:project-change-status')(f.event, 'root-a', result.operation_id)
    assert.equal(resolved.state, 'applied'); assert.equal(f.commits.length, 1); assert.equal('digest' in resolved, false)
  }
})

test('read-only records and originals are bounded, grant-bound, and stripped to renderer fields', async t => {
  const f = await fixture(t); f.behavior.confirm = { response: 1 }
  const changed = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
  const list = await f.handlers.get('campus:project-changes')(f.event, 'root-a')
  assert.equal(list.records[0].operation_id, changed.operation_id); assert.equal('digest' in list.records[0], false)
  const original = await f.handlers.get('campus:project-recovery-original')(f.event, 'root-a', 'recovery-a')
  assert.deepEqual(JSON.parse(JSON.stringify(original)), { text: 'original fixture\r\n', bom: true, newline: 'crlf' })
  f.behavior.original = () => ({ text: 'x'.repeat(12001), bom: false, newline: 'none' })
  await assert.rejects(f.handlers.get('campus:project-recovery-original')(f.event, 'root-a', 'recovery-a'), /project_change_invalid_response/)
  f.behavior.list = () => ({ available: true, records: Array(65).fill(receipt('root-a', { operation_id: 'op', subject_id: 'proposal-a', action: 'apply', digest: 'a'.repeat(64) })) })
  await assert.rejects(f.handlers.get('campus:project-changes')(f.event, 'root-a'), /project_change_invalid_response/)
})

test('backup materials use the existing read-only bridge and strip private or executable metadata', async t => {
  const f = await fixture(t)
  const archiveId = `backup_${'a'.repeat(64)}`
  f.behavior.list = () => ({ available: true, records: [], archives: [{ archive_id: archiveId,
    path: 'src/main.ts', summary: 'Backup material', created_at: '2026-10-31T12:00:00Z', size_bytes: 18,
    root_key: '[1,2]', original_base64: 'c2VjcmV0', text: 'secret', token: 'private', can_revert: true, action: 'revert' }] })
  const list = await f.handlers.get('campus:project-changes')(f.event, 'root-a')
  assert.deepEqual(JSON.parse(JSON.stringify(list)), { available: true, records: [], archives: [{ archive_id: archiveId,
    path: 'src/main.ts', summary: 'Backup material', created_at: '2026-10-31T12:00:00Z', size_bytes: 18 }] })
  f.behavior.original = (projectId, recoveryId) => {
    assert.equal(projectId, 'root-a'); assert.equal(recoveryId, archiveId)
    return { text: 'backup original\r\n', bom: false, newline: 'crlf', root_key: '[1,2]', token: 'private' }
  }
  const original = await f.handlers.get('campus:project-recovery-original')(f.event, 'root-a', archiveId)
  assert.deepEqual(JSON.parse(JSON.stringify(original)), { text: 'backup original\r\n', bom: false, newline: 'crlf' })
  assert.equal(f.prepares.length, 0); assert.equal(f.commits.length, 0); assert.equal(f.dialogs.length, 0)
  f.behavior.list = () => ({ available: true, records: [], archives: [{ archive_id: archiveId, path: '../escape',
    summary: 'Backup material', created_at: '2026-10-31T12:00:00Z', size_bytes: 18 }] })
  await assert.rejects(f.handlers.get('campus:project-changes')(f.event, 'root-a'), /project_change_invalid_response/)
})

test('a failed result query preserves uncertainty instead of claiming the write failed', async t => {
  const f = await fixture(t); f.behavior.confirm = { response: 1 }
  f.behavior.status = () => { throw new Error('private backend details') }
  const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
  assert.equal(result.state, 'uncertain'); assert.equal(f.commits.length, 1)
  await assert.rejects(f.handlers.get('campus:project-change-status')(f.event, 'root-a', result.operation_id), /project_change_failed/)
})

test('renderer HTTP headers never carry either native project privilege', async t => {
  const f = await fixture(t)
  let headers
  f.requests.headers({ url: 'http://127.0.0.1:53321/api/projects/root-a/changes/commit', webContentsId: 17,
    requestHeaders: { 'x-campus-project-write': 'renderer-token', 'X-Campus-Project-Grant': 'renderer-grant', 'x-campus-desktop-token': 'renderer-desktop', Accept: 'application/json' } }, value => { headers = value.requestHeaders })
  assert.equal(headers['x-campus-project-write'], undefined); assert.equal(headers['X-Campus-Project-Grant'], undefined)
  assert.equal(headers['x-campus-desktop-token'], undefined); assert.equal(headers['X-Campus-Desktop-Token'], 'desktop-secret')
  f.requests.headers({ url: 'https://evil.example', webContentsId: 17,
    requestHeaders: { 'X-Campus-Project-Write': 'renderer-token', 'X-Campus-Desktop-Token': 'renderer-desktop' } }, value => { headers = value.requestHeaders })
  assert.equal(Object.keys(headers).length, 0)
  const info = f.handlers.get('campus:info')(f.event)
  assert.equal(JSON.stringify(info).includes('secret'), false)
})

test('invalid prepare metadata and explicit conflicts never open a misleading confirmation', async t => {
  for (const mode of ['path', 'digest', 'conflict']) {
    const f = await fixture(t)
    f.behavior.prepare = (...args) => {
      if (mode === 'conflict') throw { code: 'project_change_conflict', status: 409 }
      return { ...preparation(...args), ...(mode === 'path' ? { path: 'C:/private-root/file.ts' } : { digest: 'not-a-digest' }) }
    }
    const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
    assert.equal(result.state, mode === 'conflict' ? 'conflict' : 'failed')
    assert.equal(f.dialogs.length, 0); assert.equal(f.commits.length, 0)
    assert.equal(JSON.stringify(result).includes('private-root'), false)
  }
})

test('confirmation binds a snapshot of the prepared digest and metadata', async t => {
  const f = await fixture(t); f.behavior.confirm = { response: 1 }
  const metadata = preparation('root-a', 'proposal-a', 'apply')
  f.behavior.prepare = () => metadata
  f.behavior.confirmHook = async () => { metadata.digest = 'd'.repeat(64); metadata.path = 'other.ts' }
  const result = await f.handlers.get('campus:change-project-file')(f.event, 'root-a', 'proposal-a', 'apply')
  assert.equal(f.commits[0][1].digest, 'a'.repeat(64))
  assert.equal(result.path, 'src/main.ts')
})

test('read-only calls reject replaced senders and result queries reject mismatching receipts', async t => {
  const f = await fixture(t)
  f.behavior.list = () => { f.web.mainFrame = { url: 'https://evil.example' }; return { available: true, records: [] } }
  await assert.rejects(f.handlers.get('campus:project-changes')(f.event, 'root-a'), /project_change_sender/)
  f.web.mainFrame = f.event.senderFrame
  f.behavior.status = () => receipt('other-root', { operation_id: 'operation-a', subject_id: 'proposal-a', action: 'apply', digest: 'a'.repeat(64) })
  await assert.rejects(f.handlers.get('campus:project-change-status')(f.event, 'root-a', 'operation-a'), /project_change_invalid_response/)
  f.behavior.status = () => ({ ...receipt('root-a', { operation_id: 'operation-a', subject_id: 'proposal-a', action: 'apply', digest: 'a'.repeat(64) }), subject_id: 'different-proposal' })
  await assert.rejects(f.handlers.get('campus:project-change-status')(f.event, 'root-a', 'operation-a'), /project_change_invalid_response/)
})
