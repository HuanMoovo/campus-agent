'use strict'

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('campusDesktop', Object.freeze({
  isDesktop: true,
  getInfo: () => ipcRenderer.invoke('campus:info'),
  loadWorkspace: () => ipcRenderer.invoke('campus:load-workspace'),
  saveWorkspace: value => ipcRenderer.invoke('campus:save-workspace', value),
  setProjectPermission: value => ipcRenderer.invoke('campus:set-project-permission', value),
  openDataFolder: () => ipcRenderer.invoke('campus:open-data'),
  openBaike: query => ipcRenderer.invoke('campus:open-baike', query),
  openOllamaDownload: () => ipcRenderer.invoke('campus:open-ollama-download'),
  restart: () => ipcRenderer.invoke('campus:restart'),
  saveBackup: (name, bytes) => ipcRenderer.invoke('campus:save-backup', { name, bytes }),
  saveExport: (name, bytes) => ipcRenderer.invoke('campus:save-export', { name, bytes }),
  pickBackup: () => ipcRenderer.invoke('campus:pick-backup'),
  pickProject: () => ipcRenderer.invoke('campus:pick-project'),
  changeProjectFile: (projectId, subjectId, action) => ipcRenderer.invoke('campus:change-project-file', projectId, subjectId, action),
  projectChangeStatus: (projectId, operationId) => ipcRenderer.invoke('campus:project-change-status', projectId, operationId),
  projectChanges: projectId => ipcRenderer.invoke('campus:project-changes', projectId),
  projectRecoveryOriginal: (projectId, recoveryId) => ipcRenderer.invoke('campus:project-recovery-original', projectId, recoveryId),
  readLog: () => ipcRenderer.invoke('campus:read-log'),
  openExternal: url => ipcRenderer.invoke('campus:open-external-https', url),
}))
