'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const vm = require('node:vm')

test('desktop main process confines requests and IPC and waits for backend shutdown', async t => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'campus-main-test-'))
  t.after(() => {
    assert.ok(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep))
    assert.ok(path.basename(temporary).startsWith('campus-main-test-'))
    fs.rmSync(temporary, { recursive: true, force: true })
  })
  const handlers = new Map()
  const requests = {}
  let activeWindow
  let backendStopped = false
  let processQuit = false
  let startup
  let openedPath
  let revealedPath
  let externalUrl
  let openPathError = ''
  let openPathRejected = false
  let menu
  let userData = temporary
  const app = new EventEmitter()
  Object.assign(app, {
    setName() {}, setAppUserModelId() {}, setPath(_key, value) { userData = value },
    getPath(key) { return key === 'appData' ? temporary : userData },
    getVersion() { return '1.0.0' }, requestSingleInstanceLock() { return true },
    isPackaged: true,
    whenReady() { return { then(callback) { startup = Promise.resolve().then(callback); return startup } } },
    quit() {
      const event = { prevented: false, preventDefault() { this.prevented = true } }
      app.emit('before-quit', event)
      if (!event.prevented) processQuit = true
    },
    relaunch() {},
  })
  class BrowserWindow extends EventEmitter {
    constructor(options) {
      super()
      this.options = options
      this.webContents = new EventEmitter()
      this.webContents.id = 17
      this.webContents.mainFrame = { url: '' }
      const session = new EventEmitter()
      session.webRequest = {
        onBeforeRequest(callback) { requests.before = callback },
        onBeforeSendHeaders(callback) { requests.headers = callback },
        onHeadersReceived(callback) { requests.response = callback },
      }
      session.setPermissionRequestHandler = callback => { requests.permission = callback }
      session.setPermissionCheckHandler = callback => { requests.checkPermission = callback }
      this.webContents.session = session
      this.webContents.setWindowOpenHandler = callback => { requests.open = callback }
      activeWindow = this
    }
    async loadURL(url) { this.webContents.mainFrame.url = url; this.emit('ready-to-show') }
    show() {} focus() {} isMinimized() { return false } restore() {}
  }
  const mockElectron = {
    nativeTheme: { themeSource: 'system', shouldUseDarkColors: false },
    app, BrowserWindow, ipcMain: { handle(name, handler) { handlers.set(name, handler) } },
    Menu: { buildFromTemplate(value) { return value }, setApplicationMenu(value) { menu = value } },
    shell: {
      async openPath(value) { openedPath = value; if (openPathRejected) throw new Error('位置不可用'); return openPathError },
      showItemInFolder(value) { revealedPath = value },
      async openExternal(value) { externalUrl = value },
    },
    dialog: { showErrorBox(_title, message) { throw new Error(message) }, showMessageBox() {} },
  }
  const directory = path.resolve(__dirname, '..')
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'main.cjs'), 'utf8'), {
    require(name) {
      if (name === 'electron') return mockElectron
      if (name === './lib/backend.cjs') return { startBackend() { return {
        ready: Promise.resolve({ origin: 'http://127.0.0.1:53321', token: 'test-token' }),
        async stop() { await Promise.resolve(); backendStopped = true },
      } } }
      return name.startsWith('.') ? require(path.join(directory, name)) : require(name)
    },
    __dirname: directory, process: { platform: 'win32', resourcesPath: temporary },
  }, { filename: 'desktop/main.cjs' })
  await startup
  const web = activeWindow.webContents
  const valid = { sender: web, senderFrame: web.mainFrame }
  assert.equal(activeWindow.options.webPreferences.nodeIntegration, false)
  assert.equal(activeWindow.options.webPreferences.contextIsolation, true)
  assert.equal(activeWindow.options.webPreferences.sandbox, true)
  assert.equal(requests.open().action, 'deny')
  assert.equal(requests.checkPermission(), false)
  let cancelled
  requests.before({ url: 'https://untrusted.example/' }, value => { cancelled = value.cancel })
  assert.equal(cancelled, true)
  requests.before({ url: 'http://127.0.0.1:53321/api/chat' }, value => { cancelled = value.cancel })
  assert.equal(cancelled, false)
  let headers
  requests.headers({ url: 'http://127.0.0.1:53321/api/chat', webContentsId: 17, requestHeaders: {} }, value => { headers = value.requestHeaders })
  assert.equal(headers['X-Campus-Desktop-Token'], 'test-token')
  requests.headers({ url: 'https://untrusted.example/', webContentsId: 17, requestHeaders: {} }, value => { headers = value.requestHeaders })
  assert.equal(headers['X-Campus-Desktop-Token'], undefined)
  const info = handlers.get('campus:info')(valid)
  assert.equal(info.version, '1.0.0')
  assert.equal(info.dataPath, path.join(temporary, 'CampusAgent'))
  assert.equal('token' in info, false)
  assert.throws(() => handlers.get('campus:info')({ sender: web, senderFrame: { url: 'http://127.0.0.1:53321' } }))
  handlers.get('campus:save-workspace')(valid, { model: 'deepseek', conversationId: 'c-123' })
  assert.equal(JSON.parse(fs.readFileSync(path.join(info.dataPath, 'workspace.json'), 'utf8')).conversationId, 'c-123')
  assert.match(JSON.parse(fs.readFileSync(path.join(info.dataPath, 'workspace.json'), 'utf8')).clientId, /^[0-9a-f-]{36}$/)
  assert.throws(() => handlers.get('campus:save-workspace')(valid, { clientId: '../escape' }))
  handlers.get('campus:save-workspace')(valid, { appearance: 'dark', accentColor: '#123abc', localModel: 'qwen3:1.7b' })
  assert.equal(mockElectron.nativeTheme.themeSource, 'dark')
  const savedWorkspace = JSON.parse(fs.readFileSync(path.join(info.dataPath, 'workspace.json'), 'utf8'))
  assert.equal(savedWorkspace.accentColor, '#123abc')
  assert.equal(savedWorkspace.localModel, 'qwen3:1.7b')
  assert.equal(savedWorkspace.conversationId, 'c-123')
  assert.throws(() => handlers.get('campus:save-workspace')(valid, { path: '../secret' }))
  await handlers.get('campus:open-data')(valid)
  assert.equal(openedPath, info.dataPath)
  assert.equal(fs.statSync(openedPath).isDirectory(), true)
  assert.equal(revealedPath, undefined)
  openPathError = '位置不可用'
  assert.equal(await handlers.get('campus:open-data')(valid), info.dataPath)
  assert.equal(revealedPath, info.dataPath)
  revealedPath = undefined
  openPathRejected = true
  await handlers.get('campus:open-data')(valid)
  assert.equal(revealedPath, info.dataPath)
  revealedPath = undefined
  menu[0].submenu[0].click()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(revealedPath, info.dataPath)
  await assert.rejects(handlers.get('campus:open-data')({ sender: web, senderFrame: { url: 'https://evil.example' } }))
  await handlers.get('campus:open-baike')(valid, '  人工智能 & next=https://evil.example/#登录  ')
  const parsed = new URL(externalUrl)
  assert.equal(parsed.origin, 'https://baike.baidu.com')
  assert.equal(parsed.pathname, '/search/word')
  assert.deepEqual([...parsed.searchParams.keys()], ['word'])
  assert.equal(parsed.searchParams.get('word'), '人工智能 & next=https://evil.example/#登录')
  assert.equal(parsed.hash, '')
  externalUrl = undefined
  for (const query of [null, {}, '', ' \t ', 'a'.repeat(201), 'test\nquery', '\ud800']) {
    await assert.rejects(handlers.get('campus:open-baike')(valid, query))
    assert.equal(externalUrl, undefined)
  }
  await assert.rejects(handlers.get('campus:open-baike')({ sender: web, senderFrame: { url: 'http://127.0.0.1:53321' } }, '大学'))
  assert.equal(externalUrl, undefined)
  await handlers.get('campus:open-ollama-download')(valid, 'https://evil.example')
  assert.equal(externalUrl, 'https://ollama.com/download/windows')
  externalUrl = undefined
  await assert.rejects(handlers.get('campus:open-ollama-download')({ sender: web, senderFrame: { url: 'https://evil.example' } }))
  assert.equal(externalUrl, undefined)
  app.quit()
  assert.equal(processQuit, false)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(backendStopped, true)
  assert.equal(processQuit, true)
})

test('preload exposes narrow browser actions without a general external URL capability', async () => {
  let exposed
  const calls = []
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '..', 'preload.cjs'), 'utf8'), {
    require(name) {
      assert.equal(name, 'electron')
      return {
        contextBridge: { exposeInMainWorld(key, value) { assert.equal(key, 'campusDesktop'); exposed = value } },
        ipcRenderer: { async invoke(...args) { calls.push(args) } },
      }
    },
  })
  assert.equal(Object.isFrozen(exposed), true)
  assert.equal('openExternal' in exposed, false)
  await exposed.openBaike('大学')
  await exposed.openOllamaDownload('https://evil.example')
  assert.deepEqual(calls, [['campus:open-baike', '大学'], ['campus:open-ollama-download']])
})
