'use strict'

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { randomBytes } = require('node:crypto')
const { parseReadyLine, PROJECT_CHANGE_CODES } = require('./policy.cjs')

function request(origin, route, token, method = 'GET', timeout = 3000, options = {}) {
  return new Promise((resolve, reject) => {
    const body = options.json === undefined ? undefined : Buffer.from(JSON.stringify(options.json), 'utf8')
    const headers = { ...options.headers, 'X-Campus-Desktop-Token': token }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      headers['Content-Length'] = body.length
    }
    const req = http.request(`${origin}${route}`, { method, headers }, res => {
      if (res.statusCode !== 200) {
        res.resume()
        reject(new Error(`Backend HTTP ${res.statusCode}`))
        return
      }
      const chunks = []
      let length = 0
      res.on('data', chunk => {
        length += chunk.length
        if (length > 1_000_000) {
          req.destroy(new Error('Response too large'))
          return
        }
        chunks.push(chunk)
      })
      res.on('aborted', () => reject(new Error('Backend response interrupted')))
      res.on('error', () => reject(new Error('Backend response interrupted')))
      res.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))) }
        catch { reject(new Error('Invalid backend response')) }
      })
    })
    req.setTimeout(timeout, () => req.destroy(new Error('Backend request timed out')))
    req.on('error', reject)
    req.end(body)
  })
}

class ProjectChangeError extends Error {
  constructor(code, status = 0) {
    const safeCode = PROJECT_CHANGE_CODES.has(code) ? code : 'project_change_failed'
    super(`[${safeCode}] 项目修改请求未完成。`)
    this.name = 'ProjectChangeError'
    this.code = safeCode
    this.status = status
  }
}

/** Private bounded transport. It never retries a request or exposes raw backend/OS errors. */
function requestChange(origin, route, token, method = 'GET', timeout = 5000, options = {}) {
  return new Promise((resolve, reject) => {
    const responseLimit = options.responseLimit ?? 1_000_000
    let settled = false
    let timer
    const finish = (error, value) => {
      if (settled) return
      settled = true; clearTimeout(timer)
      error ? reject(error) : resolve(value)
    }
    const body = options.json === undefined ? undefined : Buffer.from(JSON.stringify(options.json), 'utf8')
    const headers = { ...options.headers, 'X-Campus-Desktop-Token': token }
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = body.length }
    const req = http.request(`${origin}${route}`, { method, headers }, res => {
      if (res.statusCode !== 200) {
        res.resume()
        finish(new ProjectChangeError(res.headers['x-project-error'], res.statusCode || 0))
        return
      }
      const chunks = []; let length = 0
      res.on('data', chunk => {
        if (settled) return
        length += chunk.length
        if (length > responseLimit) { finish(new ProjectChangeError('project_change_invalid_response', 502)); req.destroy(); return }
        chunks.push(chunk)
      })
      res.on('aborted', () => finish(new ProjectChangeError('project_change_transport')))
      res.on('error', () => finish(new ProjectChangeError('project_change_transport')))
      res.on('end', () => {
        if (settled) return
        try { finish(null, JSON.parse(Buffer.concat(chunks).toString('utf8'))) }
        catch { finish(new ProjectChangeError('project_change_invalid_response', 502)) }
      })
    })
    timer = setTimeout(() => { finish(new ProjectChangeError('project_change_transport')); req.destroy() }, timeout)
    req.on('error', () => finish(new ProjectChangeError('project_change_transport')))
    req.end(body)
  })
}

function startBackend({ packaged, resourcesPath, projectRoot, dataDir, onExit, timeout = 90000, backendExecutable, frontendDirectory }) {
  const token = randomBytes(32).toString('hex')
  const projectGrantToken = randomBytes(32).toString('hex')
  const projectWriteToken = randomBytes(32).toString('hex')
  const nonce = randomBytes(24).toString('hex')
  const isWindows = process.platform === 'win32'
  const frontendDir = frontendDirectory || (packaged ? path.join(resourcesPath, 'frontend') : path.join(projectRoot, 'frontend', 'dist'))
  const command = backendExecutable || (packaged ? path.join(resourcesPath, 'backend', isWindows ? 'campus-backend.exe' : 'campus-backend')
    : path.join(projectRoot, 'backend', '.venv', ...(isWindows ? ['Scripts', 'python.exe'] : ['bin', 'python'])))
  const args = packaged ? ['--desktop'] : [path.join(projectRoot, 'backend', 'desktop_entry.py'), '--desktop']
  if (!fs.existsSync(command)) throw new Error('后端运行环境不存在，请先运行桌面安装或构建脚本。')
  if (!fs.existsSync(path.join(frontendDir, 'index.html'))) throw new Error('前端尚未编译，请先运行桌面构建脚本。')
  fs.mkdirSync(path.join(dataDir, 'logs'), { recursive: true })
  const logPath = path.join(dataDir, 'logs', 'backend.log')
  if (fs.existsSync(logPath) && fs.statSync(logPath).size > 2_000_000) {
    fs.copyFileSync(logPath, `${logPath}.previous`)
    fs.truncateSync(logPath)
  }
  const log = fs.createWriteStream(logPath, { flags: 'a' })
  log.on('error', () => {})
  let pendingLog = ''
  function logOutput(value, final = false) {
    pendingLog += String(value || '')
    for (const secret of [token, projectGrantToken, projectWriteToken, nonce]) pendingLog = pendingLog.split(secret).join('[redacted]')
    // Retain a possible split secret until the next chunk arrives.
    const end = final ? pendingLog.length : Math.max(0, pendingLog.length - 63)
    if (end) { log.write(pendingLog.slice(0, end)); pendingLog = pendingLog.slice(end) }
  }
  const env = { ...process.env, PYTHONUNBUFFERED: '1', PYTHONUTF8: '1', CAMPUS_DESKTOP_MODE: '1',
    CAMPUS_DATA_DIR: dataDir, CAMPUS_CONFIG_FILE: path.join(dataDir, '.env'), CAMPUS_FRONTEND_DIR: frontendDir,
    CAMPUS_DESKTOP_TOKEN: token, CAMPUS_DESKTOP_NONCE: nonce, CAMPUS_PROJECT_GRANT_TOKEN: projectGrantToken,
    CAMPUS_PROJECT_WRITE_TOKEN: projectWriteToken }
  const child = spawn(command, args, { cwd: dataDir, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  child.stdin.on('error', () => {})
  let origin = null
  let stopped = false
  let finished = false
  let stopping = null
  let healthy = false
  let buffer = ''
  let settle
  const startup = new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      stopped = true
      child.stdin.end()
      child.kill()
      reject(new Error('本地服务启动超时，请查看应用数据目录中的 logs/backend.log。'))
    }, timeout)
    settle = (error, value) => { clearTimeout(timer); error ? reject(error) : resolve(value) }
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', chunk => {
      if (origin) { logOutput(chunk); return }
      buffer += chunk
      if (buffer.length > 65_536) {
        stopped = true
        child.stdin.end()
        child.kill()
        settle(new Error('本地服务启动输出过长。'))
        return
      }
      let newline
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline).trim()
        buffer = buffer.slice(newline + 1)
        const ready = parseReadyLine(line, nonce)
        if (ready && !origin) {
          origin = ready.origin
          request(origin, '/api/health', token).then(health => {
            if (health.status !== 'ok') throw new Error('本地服务健康检查失败。')
            healthy = true
            settle(null, { origin, token })
          }).catch(error => { stopped = true; child.stdin.end(); child.kill(); settle(error) })
        } else logOutput(line + '\n')
      }
    })
    child.stderr.on('data', chunk => logOutput(chunk))
    child.on('error', error => { stopped = true; logOutput('', true); log.end(); settle(error) })
    child.on('exit', (code, signal) => {
      finished = true
      logOutput('', true); log.end()
      if (!healthy) settle(new Error(`本地服务未能启动（${code ?? signal}），请检查 logs/backend.log。`))
      else if (!stopped) onExit?.(code, signal)
    })
  })
  async function stop() {
    if (stopping) return stopping
    stopped = true
    stopping = (async () => {
      if (finished) return
      const exited = new Promise(resolve => { if (finished) resolve(); else child.once('exit', resolve) })
      if (origin) await request(origin, '/api/desktop/shutdown', token, 'POST', 1500).catch(() => {})
      child.stdin.end()
      await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 2000))])
      if (!finished) child.kill()
      await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 1000))])
    })()
    return stopping
  }
  async function openProject(selectedPath) {
    await startup
    if (stopped || finished) throw new Error('本地服务不可用，请重新启动程序。')
    return request(origin, '/api/projects/open', token, 'POST', 3000, {
      json: { path: selectedPath }, headers: { 'X-Campus-Project-Grant': projectGrantToken },
    })
  }
  async function changeCall(projectId, suffix, method = 'GET', json) {
    await startup
    if (stopped || finished) throw new ProjectChangeError('project_change_transport')
    return requestChange(origin, `/api/projects/${encodeURIComponent(projectId)}/changes${suffix}`, token, method, 5000, {
      ...(json === undefined ? {} : { json }), headers: { 'X-Campus-Project-Write': projectWriteToken },
      // The fixed list route includes bounded archive metadata; other responses stay small.
      responseLimit: method === 'GET' && suffix === '' ? 8 * 1024 * 1024 : 1_000_000,
    })
  }
  const prepareProjectChange = (projectId, subjectId, action) => changeCall(projectId, '/prepare', 'POST', { subject_id: subjectId, action })
  const commitProjectChange = (projectId, value) => changeCall(projectId, '/commit', 'POST', {
    subject_id: value.subject_id, action: value.action, digest: value.digest, operation_id: value.operation_id,
  })
  const projectChangeStatus = (projectId, operationId) => changeCall(projectId, `/operations/${encodeURIComponent(operationId)}`)
  const projectChanges = projectId => changeCall(projectId, '')
  const projectRecoveryOriginal = (projectId, recoveryId) => changeCall(projectId, `/${encodeURIComponent(recoveryId)}/original`)
  return { ready: startup, stop, logPath, openProject, prepareProjectChange, commitProjectChange, projectChangeStatus, projectChanges, projectRecoveryOriginal }
}

module.exports = { request, requestChange, ProjectChangeError, startBackend }
