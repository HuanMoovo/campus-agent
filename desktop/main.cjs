'use strict'

const { app, BrowserWindow, dialog, ipcMain, Menu, nativeTheme, shell } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
const { startBackend } = require('./lib/backend.cjs')
const { isOwnUrl, validateWorkspace } = require('./lib/policy.cjs')

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
let workspace = { model: 'auto', conversationId: '', localModel: '', appearance: 'system', accentColor: '#147b75' }
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
    // Two short synchronous filesystem operations serialize updates across IPC calls.
    const temporary = `${workspacePath}.tmp`
    fs.writeFileSync(temporary, JSON.stringify(updated, null, 2), { encoding: 'utf8', mode: 0o600 })
    fs.renameSync(temporary, workspacePath)
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
  bindIPC()
  nativeTheme.themeSource = workspace.appearance
  installMenu()
  window = new BrowserWindow({
    title: 'Mens', width: 1240, height: 820, minWidth: 760, minHeight: 580,
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#181b1e' : '#f5f7f7', icon: path.join(__dirname, 'assets', 'mens.png'), show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true,
      sandbox: true, webSecurity: true, allowRunningInsecureContent: false, webviewTag: false,
      devTools: !app.isPackaged,
    },
  })
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
