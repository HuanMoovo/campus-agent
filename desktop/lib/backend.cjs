'use strict'

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { randomBytes } = require('node:crypto')
const { parseReadyLine } = require('./policy.cjs')

function request(origin, route, token, method = 'GET', timeout = 3000) {
  return new Promise((resolve, reject) => {
    const req = http.request(`${origin}${route}`, { method, headers: { 'X-Campus-Desktop-Token': token } }, res => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', chunk => { body += chunk; if (body.length > 1_000_000) req.destroy(new Error('Response too large')) })
      res.on('end', () => {
        if (res.statusCode !== 200) return reject(new Error(`Backend HTTP ${res.statusCode}`))
        try { resolve(JSON.parse(body)) } catch { reject(new Error('Invalid backend response')) }
      })
    })
    req.setTimeout(timeout, () => req.destroy(new Error('Backend request timed out')))
    req.on('error', reject)
    req.end()
  })
}

function startBackend({ packaged, resourcesPath, projectRoot, dataDir, onExit, timeout = 90000, backendExecutable, frontendDirectory }) {
  const token = randomBytes(32).toString('hex')
  const nonce = randomBytes(24).toString('hex')
  const frontendDir = frontendDirectory || (packaged ? path.join(resourcesPath, 'frontend') : path.join(projectRoot, 'frontend', 'dist'))
  const command = backendExecutable || (packaged ? path.join(resourcesPath, 'backend', 'campus-backend.exe')
    : path.join(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe'))
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
  const env = { ...process.env, PYTHONUNBUFFERED: '1', PYTHONUTF8: '1', CAMPUS_DESKTOP_MODE: '1',
    CAMPUS_DATA_DIR: dataDir, CAMPUS_CONFIG_FILE: path.join(dataDir, '.env'), CAMPUS_FRONTEND_DIR: frontendDir,
    CAMPUS_DESKTOP_TOKEN: token, CAMPUS_DESKTOP_NONCE: nonce }
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
      if (origin) { log.write(chunk); return }
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
        } else log.write(line + '\n')
      }
    })
    child.stderr.on('data', chunk => log.write(chunk))
    child.on('error', error => { stopped = true; log.end(); settle(error) })
    child.on('exit', (code, signal) => {
      finished = true
      log.end()
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
  return { ready: startup, stop, logPath }
}

module.exports = { request, startBackend }
