'use strict'

const { app, BrowserWindow, dialog, ipcMain, Menu, nativeTheme, screen, shell } = require('electron')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
const { startBackend } = require('./lib/backend.cjs')
const { isOwnUrl, BACKUP_LIMIT, validateBackupBytes, validateBackupName, validateExternalUrl, validateWorkspace } = require('./lib/policy.cjs')

app.setName('Mens')
// Keep the established data path so upgrades retain the existing database and settings.
const legacyDataDir = path.join(app.getPath('appData'), 'CampusAgent')
app.setPath('userData', legacyDataDir)
app.setAppUserModelId('edu.campus.agent.desktop')
const hasLock = app.requestSingleInstanceLock()
let window = null
let backend = null
let backendOrigin = null
let backendToken = null
let quitting = false
let shutdownComplete = false
let workspace = { model: 'auto', conversationId: '', clientId: '', localModel: '', appearance: 'system', accentColor: '#147b75' }
const dataDir = app.getPath('userData')
const workspacePath = path.join(dataDir, 'workspace.json')

if (!hasLock) app.quit()
else {
  app.on('second-instance', () => {
    if (!window) return
    if (window.isMinimized()) window.restore()
    window.show()
    window.focus()
  })
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', event => {
    if (shutdownComplete) return
    event.preventDefault()
    if (quitting) return
    quitting = true
    Promise.resolve(backend?.stop()).finally(() => {
      shutdownComplete = true
      app.quit()
    })
  })
  app.whenReady().then(start).catch(fail)
}

function assertSender(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== event.sender.mainFrame
      || !isOwnUrl(event.senderFrame.url, backendOrigin)) throw new Error('不允许的桌面调用来源')
}

async function openDataDirectory() {
  fs.mkdirSync(dataDir, { recursive: true })
  let error
  try { error = await shell.openPath(dataDir) }
  catch (cause) { error = cause?.message || String(cause) }
  if (error) {
    if (typeof shell.showItemInFolder !== 'function') throw new Error(error)
    shell.showItemInFolder(dataDir)
  }
  return dataDir
}

function writeWorkspaceFile(value) {
  // Two short synchronous filesystem operations serialize updates across IPC calls.
  const temporary = `${workspacePath}.tmp`
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), { encoding: 'utf8', mode: 0o600 })
  fs.renameSync(temporary, workspacePath)
}

function clampNumber(value, min, max) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(Math.max(Math.round(value), min), max) : null
}

function visibleOnSomeDisplay(bounds) {
  try {
    return screen.getAllDisplays().some(display => {
      const area = display.workArea
      return bounds.x < area.x + area.width - 48 && bounds.x + 48 > area.x
        && bounds.y < area.y + area.height - 48 && bounds.y + 24 > area.y
    })
  } catch {
    return false
  }
}

function readWindowState() {
  try {
    const value = JSON.parse(fs.readFileSync(path.join(dataDir, 'window.json'), 'utf8'))
    const width = clampNumber(value?.width, 760, 6000)
    const height = clampNumber(value?.height, 580, 4000)
    if (!width || !height) return {}
    const state = { width, height }
    const x = clampNumber(value?.x, -20000, 20000)
    const y = clampNumber(value?.y, -20000, 20000)
    if (x !== null && y !== null && visibleOnSomeDisplay({ x, y, width, height })) Object.assign(state, { x, y })
    if (value?.maximized === true) state.maximized = true
    return state
  } catch {
    return {}
  }
}

function writeWindowState(state) {
  try {
    fs.writeFileSync(path.join(dataDir, 'window.json'), JSON.stringify(state), { encoding: 'utf8', mode: 0o600 })
  } catch { /* window state is best effort; never block shutdown on it */ }
}

function trackWindowState(target) {
  let timer = null
  const save = () => {
    if (!target || target.isDestroyed()) return
    writeWindowState({ ...target.getBounds(), maximized: target.isMaximized() })
  }
  const schedule = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(save, 400)
  }
  target.on('resize', schedule)
  target.on('move', schedule)
  target.on('close', () => {
    if (timer) clearTimeout(timer)
    save()
  })
}

function bindIPC() {
  ipcMain.handle('campus:info', event => {
    assertSender(event)
    return { version: app.getVersion(), dataPath: dataDir, platform: process.platform, packaged: app.isPackaged }
  })
  ipcMain.handle('campus:load-workspace', event => {
    assertSender(event)
    return { ...workspace }
  })
  ipcMain.handle('campus:save-workspace', (event, value) => {
    assertSender(event)
    const updated = { ...workspace, ...validateWorkspace(value) }
    writeWorkspaceFile(updated)
    workspace = updated
    nativeTheme.themeSource = workspace.appearance
    return { ...workspace }
  })
  ipcMain.handle('campus:open-data', async event => {
    assertSender(event)
    return openDataDirectory()
  })
  ipcMain.handle('campus:open-baike', async (event, query) => {
    assertSender(event)
    if (typeof query !== 'string' || !query.trim() || [...query].length > 200
        || /[\x00-\x1f\x7f-\x9f]/u.test(query)
        || [...query].some(char => char.length === 1 && /[\ud800-\udfff]/u.test(char))) throw new Error('搜索词无效')
    await shell.openExternal('https://baike.baidu.com/search/word?word=' + encodeURIComponent(query.trim()))
  })
  ipcMain.handle('campus:open-ollama-download', async event => {
    assertSender(event)
    await shell.openExternal('https://ollama.com/download/windows')
  })
  ipcMain.handle('campus:restart', event => {
    assertSender(event)
    app.relaunch()
    app.quit()
  })
  ipcMain.handle('campus:save-backup', async (event, payload) => {
    assertSender(event)
    const name = validateBackupName(payload?.name)
    const size = validateBackupBytes(payload?.bytes)
    const bytes = payload.bytes
    const view = bytes instanceof ArrayBuffer
      ? new Uint8Array(bytes)
      : new Uint8Array(bytes.buffer, bytes.byteOffset, size)
    const { canceled, filePath } = await dialog.showSaveDialog(window, {
      title: '导出 Mens 备份',
      defaultPath: path.join(app.getPath('documents'), name),
      filters: [{ name: 'Zip 备份', extensions: ['zip'] }],
    })
    if (canceled || !filePath) return { saved: false }
    fs.writeFileSync(filePath, view)
    return { saved: true, path: filePath }
  })
  ipcMain.handle('campus:pick-backup', async event => {
    assertSender(event)
    const { canceled, filePaths } = await dialog.showOpenDialog(window, {
      title: '选择 Mens 备份文件',
      properties: ['openFile'],
      filters: [{ name: 'Zip 备份', extensions: ['zip'] }],
    })
    if (canceled || !filePaths || !filePaths.length) return { picked: false }
    const stats = fs.statSync(filePaths[0])
    if (stats.size > BACKUP_LIMIT) throw new Error('备份文件超过 300 MB')
    return { picked: true, name: path.basename(filePaths[0]), bytes: fs.readFileSync(filePaths[0]) }
  })
  ipcMain.handle('campus:read-log', event => {
    assertSender(event)
    const logPath = path.join(dataDir, 'logs', 'backend.log')
    let handle = null
    try {
      const stats = fs.statSync(logPath)
      const length = Math.min(200_000, stats.size)
      const bytes = new Uint8Array(length)
      handle = fs.openSync(logPath, 'r')
      fs.readSync(handle, bytes, 0, length, stats.size - length)
      return { available: true, path: logPath, text: new TextDecoder('utf-8').decode(bytes) }
    } catch {
      return { available: false, path: logPath, text: '' }
    } finally {
      if (handle !== null) fs.closeSync(handle)
    }
  })

  ipcMain.handle('campus:open-external-https', async (event, url) => {
    assertSender(event)
    await shell.openExternal(validateExternalUrl(url))
  })
}

function installMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'Mens', submenu: [
      { label: '打开数据目录', click: () => { void openDataDirectory().catch(error => dialog.showErrorBox('无法打开数据目录', error.message)) } },
      { label: '重新启动', click: () => { app.relaunch(); app.quit() } },
      { type: 'separator' },
      { label: '退出', accelerator: 'Alt+F4', click: () => app.quit() },
    ] },
    { label: '编辑', submenu: [
      { label: '撤销', role: 'undo' }, { label: '重做', role: 'redo' }, { type: 'separator' },
      { label: '剪切', role: 'cut' }, { label: '复制', role: 'copy' }, { label: '粘贴', role: 'paste' }, { label: '全选', role: 'selectAll' },
    ] },
    { label: '视图', submenu: [
      { label: '重新加载', role: 'reload' }, { label: '实际大小', role: 'resetZoom' },
      { label: '放大', role: 'zoomIn' }, { label: '缩小', role: 'zoomOut' },
      { label: '全屏', role: 'togglefullscreen' },
    ] },
    { label: '帮助', submenu: [{ label: '关于 Mens', click: () => dialog.showMessageBox(window, {
      type: 'info', title: 'Mens', message: `Mens ${app.getVersion()}`,
      detail: '校园办事问答与有限工具调用助手。\n未配置校园数据接口的业务使用演示数据。\n本地数据保存在：' + dataDir,
    }) }] },
  ]))
}

async function start() {
  fs.mkdirSync(dataDir, { recursive: true })
  const configFile = path.join(dataDir, '.env')
  if (!fs.existsSync(configFile)) {
    const config = '# Mens desktop settings. Restart the app after editing.\n'
      + 'QWEN_API_KEY=\nDEEPSEEK_API_KEY=\nQWEN_MODEL=qwen3-235b-a22b\nDEEPSEEK_MODEL=deepseek-chat\n'
      + 'ENABLE_RAG=false\nBGE_MODEL_NAME=BAAI/bge-m3\nPLUGIN_ALLOWED_HOSTS=\n'
    fs.writeFileSync(configFile, config, { encoding: 'utf8', flag: 'wx', mode: 0o600 })
  }
  if (fs.existsSync(workspacePath)) {
    try { workspace = { ...workspace, ...validateWorkspace(JSON.parse(fs.readFileSync(workspacePath, 'utf8'))) } }
    catch { /* Corrupt preferences must not prevent startup; do not touch the database. */ }
  }
  if (!workspace.clientId) {
    workspace.clientId = crypto.randomUUID()
    try { writeWorkspaceFile(workspace) } catch { /* the generated ID still scopes this session */ }
  }
  bindIPC()
  nativeTheme.themeSource = workspace.appearance
  installMenu()
  const { maximized, ...windowState } = readWindowState()
  window = new BrowserWindow({
    title: 'Mens', width: 1240, height: 820, minWidth: 760, minHeight: 580, ...windowState,
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#181b1e' : '#f5f7f7', icon: path.join(__dirname, 'assets', 'mens.png'), show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true,
      sandbox: true, webSecurity: true, allowRunningInsecureContent: false, webviewTag: false,
      devTools: !app.isPackaged,
    },
  })
  if (maximized) window.maximize()
  trackWindowState(window)
  window.once('ready-to-show', () => { if (window && !quitting) window.show() })
  window.on('closed', () => { window = null })
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-attach-webview', event => event.preventDefault())
  window.webContents.on('will-navigate', (event, url) => { if (!isOwnUrl(url, backendOrigin)) event.preventDefault() })
  window.webContents.on('will-redirect', (event, url) => { if (!isOwnUrl(url, backendOrigin)) event.preventDefault() })
  const session = window.webContents.session
  session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  session.setPermissionCheckHandler(() => false)
  session.on('will-download', event => event.preventDefault())
  const loading = pathToFileURL(path.join(__dirname, 'assets', 'loading.html')).href
  session.webRequest.onBeforeRequest((details, callback) => {
    callback({ cancel: details.url !== loading && !isOwnUrl(details.url, backendOrigin) })
  })
  session.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders }
    if (isOwnUrl(details.url, backendOrigin) && details.webContentsId === window?.webContents.id) {
      headers['X-Campus-Desktop-Token'] = backendToken
    }
    callback({ requestHeaders: headers })
  })
  session.webRequest.onHeadersReceived((details, callback) => {
    const headers = { ...details.responseHeaders }
    if (isOwnUrl(details.url, backendOrigin)) {
      headers['Content-Security-Policy'] = ["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"]
    }
    callback({ responseHeaders: headers })
  })
  await window.loadURL(loading)
  if (quitting) return
  backend = startBackend({
    packaged: app.isPackaged, resourcesPath: process.resourcesPath,
    projectRoot: path.resolve(__dirname, '..'), dataDir,
    onExit: () => { if (!quitting) fail(new Error('本地服务意外退出。请重新启动程序；日志位于应用数据目录。')) },
  })
  const result = await backend.ready
  if (quitting || !window) return
  backendOrigin = result.origin
  backendToken = result.token
  await window.loadURL(backendOrigin)
}

function fail(error) {
  if (quitting) return
  dialog.showErrorBox('Mens 无法启动', `${error.message}\n\n数据目录：${dataDir}`)
  app.quit()
}
