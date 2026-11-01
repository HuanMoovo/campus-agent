'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { PassThrough } = require('node:stream')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const http = require('node:http')
const vm = require('node:vm')
const { request } = require('../lib/backend.cjs')

async function fixture(t, handler) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'campus-project-grant-'))
  const children = []
  const server = http.createServer((req, res) => {
    if (req.url === '/api/health') { res.end('{"status":"ok"}'); return }
    handler(req, res)
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  t.after(async () => {
    for (const { child } of children) child.kill()
    await new Promise(resolve => server.close(resolve))
    await new Promise(resolve => setImmediate(resolve))
    assert.ok(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep))
    assert.ok(path.basename(temporary).startsWith('campus-project-grant-'))
    fs.rmSync(temporary, { recursive: true, force: true })
  })
  fs.writeFileSync(path.join(temporary, 'index.html'), '<html></html>')
  const executable = path.join(temporary, 'synthetic-backend')
  fs.writeFileSync(executable, '')
  const module = { exports: {} }
  const directory = path.resolve(__dirname, '..', 'lib')
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'backend.cjs'), 'utf8'), {
    require(name) {
      if (name === 'node:child_process') return { spawn(_command, _args, options) {
        const child = new EventEmitter()
        child.stdin = new PassThrough()
        child.stdout = new PassThrough()
        child.stderr = new PassThrough()
        let exited = false
        child.kill = () => { if (!exited) { exited = true; child.emit('exit', 0, null) } }
        children.push({ child, env: options.env })
        setImmediate(() => child.stdout.write(JSON.stringify({
          event: 'campus-ready', nonce: options.env.CAMPUS_DESKTOP_NONCE,
          host: '127.0.0.1', port: server.address().port,
        }) + '\n'))
        return child
      } }
      return name.startsWith('.') ? require(path.join(directory, name)) : require(name)
    }, module, exports: module.exports, process, setTimeout, clearTimeout, Buffer,
  }, { filename: 'desktop/lib/backend.cjs' })
  function start() {
    return module.exports.startBackend({
      packaged: true, resourcesPath: temporary, projectRoot: temporary,
      dataDir: path.join(temporary, `data-${children.length}`),
      backendExecutable: executable, frontendDirectory: temporary, timeout: 1000,
    })
  }
  return { start, children, origin, temporary }
}

test('native project open privately sends an independent random grant and JSON body', async t => {
  const received = []
  let grant
  const status = { available: true, project: { id: 'opaque-id', name: 'synthetic-project' },
    limits: { max_files: 4, max_context_chars: 16000 } }
  const f = await fixture(t, (req, res) => {
    let body = ''
    req.setEncoding('utf8')
    req.on('data', chunk => { body += chunk })
    req.on('end', () => {
      received.push({ method: req.method, url: req.url, headers: req.headers, body })
      if (req.headers['x-campus-project-grant'] !== grant) {
        res.statusCode = 403
        res.end('{"detail":"private grant required"}')
      } else res.end(JSON.stringify(status))
    })
  })
  const backend = f.start()
  const ready = await backend.ready
  grant = f.children[0].env.CAMPUS_PROJECT_GRANT_TOKEN
  assert.match(grant || '', /^[0-9a-f]{64}$/)
  assert.notEqual(grant, ready.token)
  assert.notEqual(grant, f.children[0].env.CAMPUS_DESKTOP_NONCE)
  assert.deepEqual(Object.keys(ready).sort(), ['origin', 'token'])
  assert.deepEqual(Object.keys(backend).sort(), ['commitProjectChange', 'logPath', 'openProject', 'prepareProjectChange', 'projectChangeStatus', 'projectChanges', 'projectRecoveryOriginal', 'ready', 'stop'])
  assert.equal(JSON.stringify(ready).includes(grant), false)
  const nativePath = path.join(f.temporary, 'synthetic-project-项目')
  const result = await backend.openProject(nativePath)
  assert.deepEqual(JSON.parse(JSON.stringify(result)), status)
  assert.deepEqual(received[0].method, 'POST')
  assert.equal(received[0].url, '/api/projects/open')
  assert.equal(received[0].headers['x-campus-desktop-token'], ready.token)
  assert.equal(received[0].headers['x-campus-project-grant'], grant)
  assert.equal(received[0].headers['content-type'], 'application/json')
  assert.deepEqual(JSON.parse(received[0].body), { path: nativePath })
  assert.equal(Number(received[0].headers['content-length']), Buffer.byteLength(received[0].body))
  await assert.rejects(request(ready.origin, '/api/projects/open', ready.token, 'POST'), /Backend HTTP 403/)
  const other = f.start()
  await other.ready
  assert.match(f.children[1].env.CAMPUS_PROJECT_GRANT_TOKEN, /^[0-9a-f]{64}$/)
  assert.notEqual(f.children[1].env.CAMPUS_PROJECT_GRANT_TOKEN, grant)
  assert.equal(fs.readFileSync(backend.logPath, 'utf8').includes(grant), false)
})

test('project writes use a separate private token and fixed narrow routes', async t => {
  const received = []
  const f = await fixture(t, (req, res) => {
    let body = ''
    req.setEncoding('utf8'); req.on('data', chunk => { body += chunk })
    req.on('end', () => { received.push({ route: req.url, method: req.method, headers: req.headers, body }); res.end('{"fixture":true}') })
  })
  const backend = f.start(); const ready = await backend.ready
  const secret = f.children[0].env.CAMPUS_PROJECT_WRITE_TOKEN
  assert.match(secret || '', /^[0-9a-f]{64}$/)
  assert.notEqual(secret, ready.token)
  assert.notEqual(secret, f.children[0].env.CAMPUS_PROJECT_GRANT_TOKEN)
  assert.equal(JSON.stringify(ready).includes(secret), false)
  await backend.prepareProjectChange('root-a', 'proposal-a', 'apply')
  await backend.commitProjectChange('root-a', { subject_id: 'proposal-a', action: 'apply', digest: 'a'.repeat(64), operation_id: 'operation-a' })
  await backend.projectChangeStatus('root-a', 'operation-a')
  await backend.projectChanges('root-a')
  await backend.projectRecoveryOriginal('root-a', 'recovery-a')
  assert.deepEqual(received.map(row => [row.method, row.route]), [
    ['POST', '/api/projects/root-a/changes/prepare'], ['POST', '/api/projects/root-a/changes/commit'],
    ['GET', '/api/projects/root-a/changes/operations/operation-a'], ['GET', '/api/projects/root-a/changes'],
    ['GET', '/api/projects/root-a/changes/recovery-a/original'],
  ])
  assert.deepEqual(JSON.parse(received[0].body), { subject_id: 'proposal-a', action: 'apply' })
  assert.equal(received[0].headers['x-campus-project-write'], secret)
  assert.equal(received[1].headers['x-campus-project-write'], secret)
  assert.equal(fs.readFileSync(backend.logPath, 'utf8').includes(secret), false)
  f.children[0].child.stderr.write(secret.slice(0, 31))
  f.children[0].child.stderr.write(secret.slice(31) + '\n' + 'safe log fixture'.repeat(12))
  await new Promise(resolve => setImmediate(resolve))
  await new Promise(resolve => setImmediate(resolve))
  const logged = fs.readFileSync(backend.logPath, 'utf8')
  assert.equal(logged.includes(secret), false)
  assert.equal(logged.includes('[redacted]'), true)
  const other = f.start(); await other.ready
  assert.notEqual(f.children[1].env.CAMPUS_PROJECT_WRITE_TOKEN, secret)
})

test('private change transport preserves safe status codes and does not retry an uncertain commit', async t => {
  let commits = 0
  const f = await fixture(t, (req, res) => {
    if (req.url === '/conflict') { res.writeHead(409, { 'X-Project-Error': 'project_change_conflict' }); res.end('C:/private-root/secret'); return }
    if (req.url === '/commit') { commits++; return }
    res.end('{"state":"applied"}')
  })
  const { requestChange } = require('../lib/backend.cjs')
  await assert.rejects(requestChange(f.origin, '/conflict', 'token'), error => error.name === 'ProjectChangeError' && error.code === 'project_change_conflict' && error.status === 409 && !error.message.includes('private-root'))
  await assert.rejects(requestChange(f.origin, '/commit', 'token', 'POST', 30, { json: {} }), error => error.code === 'project_change_transport' && error.status === 0)
  assert.deepEqual(await requestChange(f.origin, '/status', 'token'), { state: 'applied' })
  assert.equal(commits, 1)
})

test('private change transport rejects unsafe error headers and malformed response bodies', async t => {
  const f = await fixture(t, (req, res) => {
    if (req.url === '/error') { res.writeHead(422, { 'X-Project-Error': 'C:/secret-root/token' }); res.end('private details'); return }
    if (req.url === '/oversized') { res.end(JSON.stringify({ text: 'x'.repeat(1_000_001) })); return }
    res.end('not JSON: private details')
  })
  const { requestChange } = require('../lib/backend.cjs')
  await assert.rejects(requestChange(f.origin, '/error', 'token'), error => error.code === 'project_change_failed' && error.status === 422 && !error.message.includes('secret-root'))
  for (const route of ['/invalid', '/oversized']) await assert.rejects(requestChange(f.origin, route, 'token'), error => error.code === 'project_change_invalid_response')
})

test('project change lists transport valid large archive metadata within their separate bounded budget', async t => {
  const { validateProjectChangeList } = require('../lib/policy.cjs')
  const payload = { available: true, records: [], archives: Array.from({ length: 256 }, (_, index) => ({
    archive_id: `backup_${index.toString(16).padStart(64, '0')}`,
    path: Array(10).fill('项'.repeat(190)).join('/'), summary: '原'.repeat(300),
    created_at: '2026-10-31T12:00:00Z', size_bytes: 65536,
  })) }
  const json = JSON.stringify(payload)
  assert.ok(Buffer.byteLength(json) > 1_000_000)
  assert.equal(validateProjectChangeList(payload, 'root-a').archives.length, 256)
  const f = await fixture(t, (_req, res) => res.end(json))
  const backend = f.start(); await backend.ready
  const result = await backend.projectChanges('root-a')
  assert.deepEqual(JSON.parse(JSON.stringify(validateProjectChangeList(result, 'root-a'))), payload)
})

test('project list budget rejects responses over eight MiB and other change routes retain their one MB cap', async t => {
  let response = JSON.stringify({ padding: 'x'.repeat(8 * 1024 * 1024) })
  const f = await fixture(t, (_req, res) => res.end(response))
  const backend = f.start(); await backend.ready
  const invalidResponse = error => error.code === 'project_change_invalid_response' && error.status === 502
  await assert.rejects(backend.projectChanges('root-a'), invalidResponse)
  response = JSON.stringify({ text: 'x'.repeat(1_000_001) })
  await assert.rejects(backend.projectRecoveryOriginal('root-a', `backup_${'a'.repeat(64)}`, { responseLimit: 8 * 1024 * 1024 }), invalidResponse)
  await assert.rejects(backend.prepareProjectChange('root-a', 'proposal-a', 'apply'), invalidResponse)
  await assert.rejects(backend.commitProjectChange('root-a', { subject_id: 'proposal-a', action: 'apply',
    digest: 'a'.repeat(64), operation_id: 'operation-a', responseLimit: 8 * 1024 * 1024 }), invalidResponse)
  await assert.rejects(backend.projectChangeStatus('root-a', 'operation-a'), invalidResponse)
})

test('private project HTTP calls reject non-200 and invalid or oversized responses safely', async t => {
  let response = 'status'
  const f = await fixture(t, (_req, res) => {
    if (response === 'status') { res.statusCode = 422; res.end('secret backend details'); return }
    if (response === 'invalid') { res.end('not json: secret backend details'); return }
    if (response === 'oversized') { res.end(JSON.stringify({ value: '项'.repeat(400000) })); return }
    res.write('{"partial":')
    setImmediate(() => res.destroy())
  })
  const backend = f.start()
  await backend.ready
  assert.equal(typeof backend.openProject, 'function')
  await assert.rejects(backend.openProject(path.join(f.temporary, 'synthetic-project')), /^Error: Backend HTTP 422$/)
  response = 'invalid'
  await assert.rejects(backend.openProject(path.join(f.temporary, 'synthetic-project')), /^Error: Invalid backend response$/)
  response = 'oversized'
  await assert.rejects(backend.openProject(path.join(f.temporary, 'synthetic-project')), /Response too large/)
  response = 'aborted'
  await assert.rejects(backend.openProject(path.join(f.temporary, 'synthetic-project')), /Backend response interrupted|aborted|socket hang up/)
})


