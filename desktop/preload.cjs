'use strict'

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('campusDesktop', Object.freeze({
  isDesktop: true,
  getInfo: () => ipcRenderer.invoke('campus:info'),
  loadWorkspace: () => ipcRenderer.invoke('campus:load-workspace'),
  saveWorkspace: value => ipcRenderer.invoke('campus:save-workspace', value),
  openDataFolder: () => ipcRenderer.invoke('campus:open-data'),
  openBaike: query => ipcRenderer.invoke('campus:open-baike', query),
  openOllamaDownload: () => ipcRenderer.invoke('campus:open-ollama-download'),
  restart: () => ipcRenderer.invoke('campus:restart'),
  saveBackup: (name, bytes) => ipcRenderer.invoke('campus:save-backup', { name, bytes }),
  pickBackup: () => ipcRenderer.invoke('campus:pick-backup'),
  readLog: () => ipcRenderer.invoke('campus:read-log'),
  openUpdatePage: url => ipcRenderer.invoke('campus:open-update-page', url),
}))
